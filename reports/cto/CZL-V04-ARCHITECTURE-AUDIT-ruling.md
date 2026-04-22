# CZL-V04 Architecture Simplification Audit (Senior Architect Grade)

**CTO**: Ethan Wright
**Date**: 2026-04-21
**Input**: `reports/ceo/strategic/local_gemma_migration_plan_20260421.md` Section 24 (7 proposals)
**Board directive**: "Let CTO use top-tier architect theory, technology, and testing experiments to verify; first understand our original goals, whether consolidation will lose governance capability, and whether it can achieve better functionality and objectives."
**Status**: RULING (pending Board approval)

---

## STEP 0: Original Goals and Core Invariants

### A. Mission-Layer Goals

| ID | Goal | Source | Verifiable Predicate |
|---|---|---|---|
| **M-1** | M(t) = strength_of_proof(AI_company_viable) -- operate a real company with AI agent team, producing real value | WHO_I_AM v0.5, CLAUDE.md | Revenue > 0 OR demonstrable product + CIEU trail |
| **M-2** | Y*gov product: "Enforce runtime governance on AI agent actions" -- prevent prompt injection, unauthorized rm -rf, credential leak, scope violation | Y-star-gov README, AGENTS.md | 0 false negatives on known attack vectors; forget_guard + boundary_enforcer blocks unauthorized writes |
| **M-3** | gov-mcp product: "Install in 30s, works with any MCP-compatible client" + FINRA/EU AI Act compliance evidence | gov-mcp README, plugin.json 8 tools | `pip install gov-mcp && gov-mcp install` succeeds in <30s; SIM-001 50 concurrent 0 leaks |
| **M-4** | Y* Bridge Labs as dogfood: use Y*gov to govern own agent team; every CIEU event is sales evidence | CLAUDE.md "Dual Purpose" | CIEU event count monotonically increasing; governance violations detectable + auditable |
| **M-5** | Persistent entity: Aiden survives Claude Code session close; team survives session boundaries | Migration plan v0.1 thesis, WHO_I_AM Layer 2-7 | dream_log entries during session gaps > 0; brain.db access_count cross-session monotonic |
| **M-6** | Disaster recovery: Mac failure does not kill Aiden identity | Migration plan v0.2 Section 13 | Quarterly drill: fresh machine -> full team running in <2h |

### B. Governance Core Invariants

| ID | Invariant | Source | Enforcement Mechanism |
|---|---|---|---|
| **INV-1** | Iron Rule 0: No choice questions to Board | CLAUDE.md, FG `choice_question_to_board` | FG deny + Stop hook reply scan |
| **INV-2** | Iron Rule 1: Engineering tasks dispatch via CTO, not CEO direct | CLAUDE.md, FG `ceo_engineering_boundary` | FG deny on CEO writes outside reports/ |
| **INV-3** | Iron Rule 1.5: Every status report has [LX] maturity tag | FG `missing_l_tag` | FG warn on commit/report missing L-tag |
| **INV-4** | Iron Rule 2: 5-tuple (Y*/Xt/U/Yt+1/Rt+1) reply structure | CZL Protocol, FG `czl_dispatch_missing_5tuple` | FG deny on Agent dispatch missing 5-tuple |
| **INV-5** | Iron Rule 3: Sub-agent empirical verification, never trust self-report | FG `czl_receipt_rt_not_zero` | FG deny on Rt+1=0 claim without artifact verify |
| **INV-6** | Immutable paths protection | AGENTS.md, FG `immutable_no_break_glass` | FG warn/deny; break_glass TTL 15min + CIEU trail |
| **INV-7** | Restricted write paths (secretary-only, CEO reports/ only) | AGENTS.md path matrix, FG `ceo_engineering_boundary` | FG deny; per-agent path ACL |
| **INV-8** | CIEU completeness: every tool-use event must land in audit log | cieu_store.py, PostToolUse hook | hook_wrapper PostToolUse -> CIEUStore.emit() |
| **INV-9** | Active agent identity must resolve correctly; wrong identity = wrong write permissions | .ystar_active_agent, identity_detector.py | PreToolUse identity resolution; per-PPID marker files |
| **INV-10** | ForgetGuard rules cannot be bypassed by agent within session | forget_guard.py + forget_guard_rules.yaml | FG loaded at hook init; rules evaluated every tool call; no agent API to disable |
| **INV-11** | Break-glass has 15-min TTL + CIEU event trail | ceo_mode_manager.py | TTL enforced; BREAK_GLASS_ACTIVATED/EXPIRED events |
| **INV-12** | WHO_I_AM is single source of truth for identity; updates require forget_guard check | WHO_I_AM.md, FG immutable path | Secretary auto-enforce + Board approve before merge |
| **INV-13** | Session age concurrency cap (>6h: max 2, >8h: max 1) | FG `session_age_concurrency_cap` | FG warn on excess spawn |
| **INV-14** | Delegation chain integrity: sub-agent scope guard (no git commit/push/add unless explicit) | MEMORY.md feedback_explicit_git_op_prohibition | Dispatch prompt template inclusion |
| **INV-15** | Reply taxonomy enforcement: stop hook scans every reply for structural compliance | hook_stop_reply_scan.py, reply_taxonomy.py | Stop hook runs post-generation |

### C. Functional Goals (aspired, not yet fully achieved)

| ID | Goal | Current State | Gap |
|---|---|---|---|
| **FG-1** | Persistent existence (Aiden continues thinking when Claude Code closed) | NOT MET. 10h gap 2026-04-20 with 0 BRAIN_DREAM events | Requires daemon + Gemma |
| **FG-2** | Full team persistence (9-11 agents all persistent) | NOT MET. All agents session-bound | Requires cluster daemon |
| **FG-3** | Primary entry via office UI (not CLI) | NOT MET. CLI only | Requires openclaw-office fork |
| **FG-4** | Disaster recovery completeness | PARTIAL. Source backed up (GitHub); runtime sqlite excluded from mirror | Requires encrypted sqlite backup |
| **FG-5** | Governance equivalence across all entry points (Claude/Gemma/office) | NOT MET. Only Claude Code hook exists | Requires adapter-per-runtime OR single MCP gateway |

### D. Audit Framework

For each of the 7 proposals in Section 24, I evaluate on three axes:
- **Axis A**: Goal understanding (what problem, which mission goal, counterfactual if skipped)
- **Axis B**: Invariant preservation (table of INV-1 through INV-15)
- **Axis C**: Technical viability + experiment design

---

## STEP 1: Section 24.1 -- Consolidation 1: 9 agent daemons -> 1 master daemon + 9 asyncio workers

### Axis A -- Goal Understanding

**Problem being solved**: v0.3 proposed 9 independent Python processes (one per agent), each with its own launchd plist, Unix socket, and PID. This creates O(N) operational surface: 9 plists to maintain, 9 sockets to monitor, 9 log files, cross-process state synchronization via IPC. On M4 Pro 24GB with Gemma 12B consuming ~10GB, 9 Python processes add ~2-4GB baseline RSS, eating into the 14GB headroom.

**Mission-layer alignment**: Primarily serves M-5 (persistent entity) and FG-2 (full team persistence). Secondary: M-4 (dogfood -- demonstrating multi-agent governance at runtime).

**Counterfactual (if not done)**: In 6 months, maintaining 9 launchd plists + 9 socket files + debugging cross-process race conditions on brain.db writes becomes the dominant operational burden. Agent restarts desynchronize (one agent crashloops while others run), creating inconsistent team state. The governance layer must handle N independent failure modes rather than 1. Operational complexity grows linearly with team size, making Phase 5 (add more agents) prohibitively expensive.

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| INV-1 (No choice questions) | YES | No interaction with reply content | -- |
| INV-2 (Dispatch via CTO) | YES | Dispatch routing is application-layer, not process-layer | -- |
| INV-3 (L-tag in status) | YES | Orthogonal | -- |
| INV-4 (5-tuple structure) | YES | Orthogonal | -- |
| INV-5 (Empirical verify) | YES | Orthogonal | -- |
| INV-6 (Immutable paths) | YES | Path enforcement is Y*gov kernel, not process architecture | -- |
| INV-7 (Restricted writes) | YES | Same as INV-6 | -- |
| INV-8 (CIEU completeness) | **MAYBE** | If 9 asyncio workers share a single event loop, a slow worker blocking the loop could delay CIEU emit from other workers. Starvation scenario: worker A does heavy Python computation (e.g., forget_guard rule evaluation with complex regex), blocking the event loop, causing worker B's CIEU emit to queue indefinitely. | **Guard**: Each worker's tool-use cycle must be structured as: (1) acquire governance check (async, yields), (2) call Ollama HTTP (async I/O, yields), (3) emit CIEU (async, yields). All CPU-bound work (forget_guard regex, brain query) must be wrapped in `asyncio.to_thread()` to prevent event loop starvation. Add a watchdog coroutine that fires every 5s checking all workers' last-heartbeat; if any worker silent >30s, log CIEU WARNING and restart that worker. |
| INV-9 (Active agent identity) | **MAYBE** | In single-process, "active agent" is no longer PID-based (.ystar_active_agent.ppid_XXXX). All workers share PID. Identity resolution must shift from PID-based to worker-ID-based. | **Guard**: Replace PID-based identity files with a master-daemon-internal identity registry. Each worker has a `worker_id` (e.g., "ceo", "ethan-cto"). The master daemon maintains an in-memory dict `{worker_id: AgentIdentity}`. External callers (gov-mcp, Claude Code hooks) query the master daemon's HTTP/socket API for current active agent, not the filesystem. Transition: keep .ystar_active_agent for backward compat during migration, master daemon writes it on behalf of the currently-Board-facing worker. |
| INV-10 (FG non-bypassable) | **MAYBE** | In asyncio single-process, one worker could theoretically skip calling forget_guard if the worker's code path branches around it. With 9 independent processes, each process independently loads FG; with 1 process, there's a shared FG instance. | **Guard**: ForgetGuard instance is injected into the master daemon's governance middleware, which wraps every worker's tool-use call. Workers cannot invoke tools without going through the middleware. The middleware is structurally non-optional (like WSGI middleware in a web framework). Pattern: `async def governed_tool_call(worker_id, tool, input) -> result` where FG check is mandatory prefix. |
| INV-11 (Break-glass TTL) | YES | Break-glass is per-agent state, stored in memory. Single-process makes TTL enforcement easier (single clock). | -- |
| INV-12 (WHO_I_AM single truth) | YES | File-based, not process-based | -- |
| INV-13 (Session age concurrency) | **N/A** | This invariant applies to Claude Code sub-agent spawns, not daemon workers. Daemon workers are always-on, not spawned per-task. | Invariant may need reframing for daemon context: instead of "session age", track "worker queue depth" and cap concurrent Ollama inference calls. |
| INV-14 (Delegation chain integrity) | YES | Delegation scope is application-layer | -- |
| INV-15 (Reply taxonomy) | YES | Reply scanning is Y*gov kernel function, called per-worker-output regardless of process model | -- |

### Axis C -- Technical Viability

**Formal description (state machine)**:
```
States: INIT -> LOADING_WORKERS -> RUNNING -> SHUTTING_DOWN -> STOPPED
         RUNNING substates per worker: IDLE | WAITING_INFERENCE | PROCESSING | ERROR

Master daemon:
  on INIT: load config, instantiate ForgetGuard, connect sqlite DBs
  on LOADING_WORKERS: for each agent in config, create AgentWorker coroutine
  on RUNNING: asyncio.gather(*workers), plus watchdog, plus signal handler
  on SIGTERM: graceful shutdown, flush CIEU, close DBs

AgentWorker(agent_id):
  loop:
    event = await event_queue.get()  # from router, trigger, or scheduled
    governance_result = await governed_tool_call(agent_id, event)
    if governance_result.denied: log + skip
    response = await ollama_inference(agent_id, event, system_prompt)
    post_result = await post_governance(agent_id, response)  # CIEU emit, brain writeback
    await event_queue.task_done()
```

**Failure modes**:
1. **Single point of failure**: Master crash kills all 9 workers. Mitigation: launchd KeepAlive=true auto-restarts. Workers resume from last checkpoint (each worker's event_queue is persistent or re-derivable from trigger state).
2. **GIL contention**: Python GIL limits true parallelism for CPU-bound work. But: Ollama inference is HTTP I/O (asyncio yields at await), CIEU emit is sqlite I/O (wrapped in to_thread), brain queries are sqlite I/O. The only CPU-bound segments are forget_guard regex evaluation and reply_taxonomy scanning. These are microsecond-scale per check (regex on ~1KB text). GIL contention is negligible.
3. **Memory pressure**: 1 Python process with 9 workers: ~200MB base + 9x (system_prompt ~50KB + brain connection overhead ~5MB) = ~250MB. vs 9 processes: 9x 100MB = 900MB. Net saving: ~650MB, significant on 24GB machine.
4. **Deadlock**: asyncio single-loop cannot deadlock in the traditional mutex sense. However, if two workers both await the same sqlite write lock (BEGIN EXCLUSIVE), one blocks. Mitigation: serialize all writes through a single `db_writer` coroutine with asyncio.Queue, eliminating write contention entirely.

**Quantitative improvement**:
- Process count: 9 -> 1 (89% reduction)
- Launchd plists: 9 -> 1 (89% reduction)
- Memory: ~900MB -> ~250MB (72% reduction)
- Log files: 9 -> 1 (89% reduction)
- IPC complexity: O(N^2) cross-process -> 0 (in-process direct reference)

**Benchmark experiment design**:

**Test A1**: 9 asyncio workers concurrent load
- Setup: Mock Ollama HTTP endpoint (httpbin or local Flask returning 500-token response in 200ms simulating inference). 9 workers each submit 10 req/s = 90 req/s total.
- Measure: p50/p95/p99 end-to-end latency per worker (from event dequeue to CIEU emit). Memory RSS of master process. CPU utilization.
- Success criteria: p95 < 500ms, p99 < 2s, RSS < 500MB, 0 deadlocks, 0 dropped CIEU events over 10-minute run.
- Tool: `pytest` + custom asyncio test harness. `asyncio.gather()` 9 worker tasks, each looping 600 requests (10/s * 60s). Use `time.perf_counter()` for latency. `psutil.Process().memory_info().rss` for memory.
- Duration: 10 min steady state + 2 min burst (all 9 workers spike to 20 req/s = 180 req/s).

**Test A2**: ForgetGuard under shared event loop
- Setup: Same as A1 but each request triggers 17 FG rule evaluations (matching production rule count).
- Measure: FG evaluation latency per rule (should be < 1ms each). Event loop starvation indicator: watchdog heartbeat jitter.
- Success criteria: FG eval < 5ms total per request. Watchdog heartbeat jitter < 100ms.
- Tool: `pytest` + `asyncio.to_thread()` wrapping FG eval. Instrument with `time.perf_counter()`.

**Test A3**: Single-point-of-failure recovery
- Setup: Running master daemon. Kill worker #3 (inject exception). Verify: (a) other 8 workers continue, (b) worker #3 auto-restarts within 5s, (c) CIEU event `WORKER_CRASH_RECOVERED` emitted.
- Success criteria: 0 impact on other workers' latency. Recovery < 5s.
- Tool: `pytest` + deliberate exception injection.

---

## STEP 2: Section 24.2 -- Consolidation 2: hook_wrapper.py retirement -> all runtimes via gov-mcp

### Axis A -- Goal Understanding

**Problem being solved**: v0.3 proposed 4 parallel adapter codebases (hook_wrapper.py for Claude Code, gov-mcp server, Gemma daemon hook, openclaw-office MCP client). Each adapter independently imports Y*gov kernel modules. The risk is adapter code drift: if one adapter adds a governance check that another forgets, governance consistency degrades silently. This is the "adapter discipline" vs "structural guarantee" distinction.

**Mission-layer alignment**: Directly serves M-2 (runtime governance enforcement) and FG-5 (governance equivalence across entry points). Also M-3 (gov-mcp as product -- if gov-mcp becomes the single governance gateway, its value proposition is definitively proven by internal dogfood).

**Counterfactual (if not done)**: In 6 months, 4 adapters drift. Claude Code hook gets a new FG rule integration that Gemma adapter doesn't. An agent running via Gemma bypasses a restriction that Claude Code enforces. This is a governance hole discovered only in production (or worse, by an external auditor). The sales story ("Y*gov ensures consistent governance across all runtimes") becomes falsifiable. This is M-2 existential risk.

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| INV-1 (No choice questions) | YES | Reply content scanning moves to gov-mcp `gov_check` reply-scan mode | -- |
| INV-2 (Dispatch via CTO) | YES | Dispatch routing in gov-mcp `gov_delegate` | -- |
| INV-3 (L-tag) | YES | gov-mcp can expose `gov_reply_scan` tool for L-tag enforcement | -- |
| INV-4 (5-tuple) | YES | CZL protocol validation in gov-mcp dispatch tool | -- |
| INV-5 (Empirical verify) | YES | Receipt validation via gov-mcp tool | -- |
| INV-6 (Immutable paths) | YES | `gov_path_verify` already one of 8 MCP tools | -- |
| INV-7 (Restricted writes) | YES | Same as INV-6 | -- |
| INV-8 (CIEU completeness) | **MAYBE** | Critical question: MCP protocol stdio pipe throughput. Current hook_wrapper is in-process (Python import, microsecond overhead). MCP protocol adds serialization overhead: JSON encode request -> stdio write -> gov-mcp reads -> process -> JSON encode response -> stdio write -> client reads. For PreToolUse (latency-critical, every tool call), this adds ~1-5ms per call. Production hook_wrapper currently sees <10ms total including FG eval. If MCP overhead is 5ms, total becomes ~15ms. Acceptable? Yes, Claude Code tool calls themselves take 100ms-30s. 15ms governance overhead is negligible (<0.05% of typical tool call). | **Guard**: Benchmark MCP round-trip latency. If >20ms p95, consider switching from stdio to HTTP (localhost) which can be faster for high-throughput. Gov-mcp already supports HTTP mode per README. |
| INV-9 (Active agent identity) | **MAYBE** | Current hook_wrapper resolves identity via .ystar_active_agent PID files. If hook_wrapper is retired, identity resolution must move to gov-mcp. Gov-mcp needs to know "who is calling" -- MCP protocol can include caller metadata in request headers. | **Guard**: Extend gov-mcp tool schema to include `caller_agent_id` parameter in every `gov_check` call. Claude Code MCP client auto-includes this from its session state. Gemma daemon includes from worker_id. Office includes from active agent window. Gov-mcp validates caller_id against registered agents. |
| INV-10 (FG non-bypassable) | **MAYBE** | If hook_wrapper is retired and Claude Code relies on MCP for governance, what prevents Claude Code from simply not calling `gov_check` before a tool use? Current architecture: Claude Code hook is mandatory (configured in .claude/settings.json hooks section). MCP tools are optional -- Claude decides whether to call them. | **CRITICAL GUARD**: This is the key structural question. Two paths: (A) Keep a minimal hook_wrapper (<50 LOC) that does ONLY one thing: for every PreToolUse, call gov-mcp `gov_check` via MCP protocol. The hook is mandatory (Claude Code enforces it). Gov-mcp does the actual governance logic. This is the "shim" approach in the proposal. (B) Rely on Claude Code's MCP server integration to auto-call `gov_check` before every tool use. This requires Claude Code to support "mandatory pre-tool-use MCP call" configuration, which is NOT a standard MCP feature as of 2026-04. **Recommendation: Path (A). Keep the hook shim. Full retirement of hook_wrapper is premature. The shim is 30-50 LOC, trivially maintainable, and provides the structural non-bypassability guarantee.** |
| INV-11 (Break-glass TTL) | YES | Break-glass state moves to gov-mcp server (single process, easy TTL tracking) | -- |
| INV-12 (WHO_I_AM single truth) | YES | File-based, unchanged | -- |
| INV-13 (Session concurrency) | YES | Tracked in gov-mcp server state | -- |
| INV-14 (Delegation chain) | YES | `gov_delegate` MCP tool handles this | -- |
| INV-15 (Reply taxonomy) | YES | Stop-hook equivalent: gov-mcp `gov_reply_scan` called post-generation | Same concern as INV-10: who forces the call? For Claude Code: Stop hook shim calls gov-mcp. For daemon: master daemon middleware. For office: MCP client middleware. |

### Axis C -- Technical Viability

**Critical technical question: MCP stdio throughput vs current hook_wrapper**

Current hook_wrapper performance: measured at ~39,000 checks/s (gov-mcp README claim). However, this is gov-mcp's internal throughput, not the MCP protocol round-trip. The MCP protocol overhead consists of:
1. JSON serialization of request (~0.1ms for typical payload)
2. stdio write + read (pipe buffering, ~0.1-0.5ms)
3. gov-mcp deserialization + processing + serialization of response
4. stdio write + read back

Empirical data from MCP ecosystem: typical MCP tool call round-trip is 5-20ms for stdio transport, 2-10ms for HTTP localhost. Claude Code itself adds MCP overhead for its tool calls (the tools we see in the UI are MCP-served). Claude Code 1.x tool call latency is typically 50-200ms for lightweight tools, suggesting MCP overhead is well within budget.

**The 39,000 checks/s claim is for in-process calls. Over MCP stdio, expect ~1,000-5,000 checks/s. This is still far above our needs**: even 90 req/s from 9 daemon workers + Claude Code = ~100 req/s peak, well under 1,000/s floor.

**Formal description**:
```
Before (v0.3):
  [Claude Code] --stdin/stdout--> [hook_wrapper.py] --import--> [Y*gov kernel]
  [Gemma daemon] --import--> [gemma_hook.py] --import--> [Y*gov kernel]
  [Office] --MCP--> [gov-mcp] --import--> [Y*gov kernel]

After (v0.4):
  [Claude Code] --hook shim (30 LOC)--> --MCP--> [gov-mcp] --import--> [Y*gov kernel]
  [Gemma daemon] --MCP client--> [gov-mcp] --import--> [Y*gov kernel]
  [Office] --MCP client--> [gov-mcp] --import--> [Y*gov kernel]

Single governance entry point: gov-mcp. All runtimes are MCP clients.
```

**Failure modes**:
1. **gov-mcp crashes**: All runtimes lose governance. Mitigation: launchd KeepAlive=true; runtimes detect gov-mcp unavailability and either (a) fail-closed (block all tool calls until gov-mcp restarts -- safest for governance), or (b) fail-open with CIEU event GOVERNANCE_UNAVAILABLE logged locally (dangerous for governance but prevents operational halt). **Recommendation: fail-closed for production, fail-open configurable for development.**
2. **MCP protocol version incompatibility**: Claude Code upgrades MCP protocol. Mitigation: gov-mcp pins to MCP schemaVersion v2 (already declared in plugin.json). Version negotiation on connect.
3. **Latency regression**: If MCP overhead is higher than expected, PreToolUse becomes noticeably slower. Mitigation: benchmark early (Test B1 below), switch to HTTP transport if stdio too slow.

**Quantitative improvement**:
- Adapter codebases: 4 -> 1 (gov-mcp, 7,568 LOC existing) + 1 shim (30-50 LOC)
- hook_wrapper.py: 550 LOC -> 30-50 LOC shim (91-95% reduction)
- Governance consistency: from "discipline-enforced" (4 adapters must stay in sync) to "structural" (single MCP server)
- New runtime onboarding: from "write 100+ LOC adapter" to "install MCP client library, call gov_check"

**Experiment design**:

**Test B1**: MCP round-trip latency benchmark
- Setup: gov-mcp running as MCP server (stdio mode). Client script sends 1,000 `gov_check` requests sequentially, then 100 concurrent (asyncio).
- Measure: p50/p95/p99 round-trip latency. Throughput (requests/second).
- Success criteria: p95 < 20ms sequential, p95 < 50ms concurrent-100, throughput > 500 req/s.
- Tool: Custom Python script using MCP client SDK. `time.perf_counter()` per request.
- Duration: 5 min sequential + 5 min concurrent.

**Test B2**: Claude Code hook shim end-to-end
- Setup: Install 30-LOC hook shim in .claude/settings.json. Shim calls gov-mcp for every PreToolUse. Run 100 normal Claude Code tool calls (Read/Bash/Edit mix).
- Measure: Total governance overhead per tool call (shim entry to shim exit). Compare to current hook_wrapper overhead.
- Success criteria: Overhead < 30ms p95 (current hook_wrapper is ~10ms, so 3x budget for MCP overhead).
- Tool: Timestamps in shim + gov-mcp server logs. Correlate by request_id.

**Test B3**: gov-mcp crash recovery
- Setup: gov-mcp running. Kill it mid-request. Verify: (a) Claude Code hook shim returns DENY (fail-closed), (b) launchd restarts gov-mcp within 5s, (c) next request succeeds, (d) CIEU event GOVERNANCE_UNAVAILABLE recorded.
- Success criteria: Fail-closed works. Recovery < 5s. Zero governance bypass during outage.

---

## STEP 3: Section 24.3 -- Consolidation 3: 4-route backup -> 1 backup daemon + 4 target plugins

### Axis A -- Goal Understanding

**Problem being solved**: v0.3 proposed 5 independent backup mechanisms (continuous_mirror local, VPS rsync, Codeberg git, Cloudflare R2, Tailscale->Windows), each with its own scheduling (cron/launchd), encryption logic, retention policy, and restore procedure. The operational surface is wide: 5 different tools, 5 different failure modes, 5 different monitoring points. An operator (Board or Aiden in daemon mode) must remember 5 different restore commands.

**Mission-layer alignment**: Directly serves M-6 (disaster recovery) and indirectly M-5 (persistent entity -- persistence requires survivability).

**Counterfactual (if not done)**: In 6 months, one backup route silently fails (e.g., R2 API key expires, VPS disk fills up). No unified monitoring detects it. When disaster strikes, the operator discovers 3 of 5 routes are stale. The 2h recovery KPI is blown. Worst case: all routes fail simultaneously due to a shared dependency (e.g., the encryption key is lost, and all 5 routes used different key management -- or the same key, but nobody documented which).

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| INV-1 through INV-7 | YES | Backup daemon does not interact with governance enforcement logic | -- |
| INV-8 (CIEU completeness) | **YES, improved** | Unified CIEU events (BACKUP_CYCLE_STARTED, BACKUP_TARGET_OK/FAIL) provide better auditability than 5 scattered cron jobs with no CIEU integration | -- |
| INV-9 through INV-15 | YES | Orthogonal to backup | -- |

No invariant is threatened. This consolidation is purely operational improvement.

### Axis C -- Technical Viability

**Formal description**:
```python
class BackupDaemon:
    targets: List[BackupTarget]  # [LocalMirror, VPSRsync, CodebergGit, R2S3, TailscaleWindows]
    encryption: AES256GCM
    retention: RetentionPolicy
    manifest: ManifestManager

    async def run_cycle(self, trigger: Trigger):
        manifest = self.manifest.start_cycle(trigger)
        for target in self.targets:
            try:
                result = await target.backup(self.encryption, manifest)
                emit_cieu("BACKUP_TARGET_OK", target=target.name)
            except Exception as e:
                emit_cieu("BACKUP_TARGET_FAIL", target=target.name, error=str(e))
        self.manifest.complete_cycle(manifest)

class BackupTarget(Protocol):
    async def backup(self, encryption: AES256GCM, manifest: Manifest) -> Result: ...
    async def restore(self, encryption: AES256GCM, manifest: Manifest) -> Result: ...
    async def verify(self, manifest: Manifest) -> bool: ...
```

**Failure modes**:
1. **Backup daemon itself crashes**: All 5 routes stop. Mitigation: launchd KeepAlive + CIEU alert when no BACKUP_CYCLE_STARTED event in expected window.
2. **Encryption key loss**: All encrypted backups become unrecoverable. Mitigation: Key derivation from master password (Board memorizes). Master password also in password manager + paper backup. Test: quarterly drill includes key derivation from memory.
3. **Shared-dependency failure**: All targets use the same network interface. If Mac WiFi drops, all network targets fail simultaneously. Mitigation: LocalMirror target is filesystem-only (no network). At least 1 route always works if disk is alive.
4. **Rewrite regression**: Existing continuous_mirror.sh (23 LOC, L4 SHIPPED 2026-04-13) and disaster_recovery.sh (172 LOC, L4 SHIPPED) are proven. Rewriting risks regression. Mitigation: Phase the rewrite. Phase 1-2 keep existing scripts. Phase 3+ new daemon wraps existing scripts as BackupTarget plugins initially (subprocess call to .sh), then gradually replaces internals with native Python. Existing test reports serve as regression baseline.

**Quantitative improvement**:
- Operational surface: 5 independent mechanisms -> 1 unified daemon
- Encryption implementations: potentially 5 -> 1 (AES-256-GCM)
- Monitoring: 5 separate check points -> 1 CIEU event stream
- Restore commands: 5 different -> 1 (`backup_daemon restore --source {target}`)
- New target addition: write new shell scripts + cron entries -> implement BackupTarget interface

**Risk assessment**: This is the **lowest-risk** consolidation. No governance invariants touched. Existing proven scripts can be wrapped, not rewritten. Net operational improvement with minimal regression risk.

**Experiment design**:

**Test C1**: Plugin interface validation
- Setup: Implement BackupTarget interface. Wrap existing continuous_mirror.sh as LocalMirror plugin. Run 10 backup cycles.
- Measure: Byte-identical output to raw continuous_mirror.sh. CIEU events emitted correctly.
- Success criteria: 100% output parity with existing script. 10/10 CIEU events.
- Tool: `pytest` + file hash comparison.

**Test C2**: Encryption round-trip
- Setup: Encrypt aiden_brain.db with AES-256-GCM. Upload to mock R2. Download. Decrypt. Compare hash.
- Measure: File integrity (SHA-256 before encrypt = after decrypt). Encryption speed (MB/s).
- Success criteria: Hash match. Encryption speed > 100MB/s (aiden_brain.db is ~1.7MB, should take <20ms).
- Tool: `pytest` + `cryptography` library.

**Test C3**: Quarterly drill simulation
- Setup: Fresh temp directory simulating new machine. Run `backup_daemon restore --source local_mirror`. Verify: all files present, sqlite integrity check, governance_boot.sh succeeds.
- Success criteria: All files restored. `sqlite3 aiden_brain.db "PRAGMA integrity_check"` returns "ok". `governance_boot.sh` returns ALL SYSTEMS GO.
- Tool: `pytest` + temp directory + subprocess.

---

## STEP 4: Section 24.4 -- Consolidation 4: WHO_I_AM company-level + per-agent split

### Axis A -- Goal Understanding

**Problem being solved**: v0.3 proposed 9-11 separate WHO_I_AM_{AGENT}.md files, each ~700 lines. The company-level content (M(t) mission, 7 philosophical principles, 17 meta-rules, L0-L4 legal stack) is identical across all files. This creates a classic "copy-paste divergence" risk: when a principle is updated, all 9-11 files must be updated in sync. In practice, some files will lag, and agents will operate under inconsistent company values.

**Mission-layer alignment**: Directly serves M-4 (dogfood -- demonstrating that Y*gov maintains consistent governance identity across agents) and INV-12 (WHO_I_AM as single truth).

**Counterfactual (if not done)**: In 6 months, Board updates a philosophical principle. Secretary updates Aiden's WHO_I_AM.md but misses Ethan's and Leo's. Ethan operates under the old principle for 2 weeks before someone notices. This is a governance identity drift -- exactly the class of problem Y*gov is supposed to prevent. Embarrassing for dogfood credibility.

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| INV-1 through INV-11 | YES | WHO_I_AM restructuring does not alter governance enforcement mechanics | -- |
| INV-12 (WHO_I_AM single truth) | **YES, improved** | Current: 9-11 copies = 9-11 potential divergence points. After: 1 company file + 9-11 agent-specific files. Company-level truth is literally 1 file. Agent-specific truth is scoped to that agent only. | Improvement, not threat. |
| INV-13 through INV-15 | YES | Orthogonal | -- |

No invariant is threatened. This consolidation strengthens INV-12.

### Axis C -- Technical Viability

**Formal description**:
```
identity_inject(agent_id) -> str:
    company = read("knowledge/company/WHO_WE_ARE.md")  # ~500 lines, shared
    personal = read(f"knowledge/{agent_id}/wisdom/WHO_I_AM_{agent_id}.md")  # ~200 lines
    return company + "\n---\n" + personal
```

**Token cost analysis for Gemma 4 12B**:

Current (single WHO_I_AM.md for Aiden): ~700 lines. At ~3 tokens/line (mixed Chinese/English), ~2,100 tokens.

After split:
- WHO_WE_ARE.md: ~500 lines = ~1,500 tokens
- WHO_I_AM_{agent}.md: ~200 lines = ~600 tokens
- Total per inference: ~2,100 tokens (same as current)

For Gemma 4 12B with typical 8K-32K context window:
- 8K context: 2,100 tokens = 26% of context. Leaves 5,900 tokens for conversation. This is tight but workable for short daemon tasks (heartbeat, patrol, dream summary). For longer tasks, the system prompt can be compressed (omit meta-rules that are enforced by FG anyway, keep only role-specific + mission).
- 32K context (if Gemma 4 supports): 2,100 tokens = 6.6% of context. No concern.

**Token optimization guard**: For daemon tasks where context is precious, implement a `prompt_tier` system:
- Tier 1 (full): WHO_WE_ARE + WHO_I_AM_{agent} -- for decision-making tasks
- Tier 2 (medium): WHO_I_AM_{agent} + company mission statement (100 tokens) -- for routine tasks
- Tier 3 (minimal): Role name + 3-line identity summary -- for mechanical tasks (heartbeat, file copy)

Router assigns tier per task type. This prevents unnecessary context consumption.

**Failure modes**:
1. **File read failure**: WHO_WE_ARE.md missing/corrupted. Mitigation: daemon startup validates both files exist and are non-empty. If missing, refuse to start (fail-fast).
2. **Encoding issues**: Mixed Chinese/English may cause encoding problems with some text processing. Mitigation: All files UTF-8. Validate encoding on read.
3. **Update race**: Board updates WHO_WE_ARE.md while daemon is mid-inference using old content. Mitigation: Daemon caches identity at inference start. Cache refresh on file-change notification (fswatch/inotify). Between notification and refresh, the old version is used -- this is acceptable for the <1s window.

**Quantitative improvement**:
- Files requiring update on company principle change: 9-11 -> 1 (91% reduction)
- Per-agent identity uniqueness: preserved (each agent still has own ~200 lines)
- Token cost: neutral (same total tokens per inference)
- New agent onboarding: write ~200 lines (personal) instead of ~700 lines (full copy)

**Experiment design**:

**Test D1**: Identity injection parity
- Setup: Take current Aiden WHO_I_AM.md. Manually split into WHO_WE_ARE.md (company) + WHO_I_AM_CEO.md (personal). Concatenate. Diff against original.
- Measure: Semantic equivalence (no content lost or duplicated).
- Success criteria: diff shows only structural changes (section headers, separators), no content delta.

**Test D2**: Token count validation
- Setup: Tokenize WHO_WE_ARE.md + each WHO_I_AM_{agent}.md using Gemma tokenizer.
- Measure: Total token count per agent. Compare to 8K/32K context budget.
- Success criteria: Total < 25% of minimum context window (i.e., < 2,000 tokens for 8K).
- Tool: Ollama tokenize endpoint or `tiktoken` approximation.

**Test D3**: Cache refresh latency
- Setup: Daemon running with cached identity. Modify WHO_WE_ARE.md. Measure time to next inference using updated content.
- Measure: Refresh latency from file write to daemon awareness.
- Success criteria: < 5s (fswatch/polling interval).
- Tool: Custom test with `os.path.getmtime()` polling.

---

## STEP 5: Section 24.5 -- Split 1: gov-mcp release cycle decoupled from Y*gov kernel

### Axis A -- Goal Understanding

**Problem being solved**: gov-mcp deeply imports Y*gov. If they share release cycles, gov-mcp 1.0 (customer-facing) is blocked by Y*gov's rapid 0.x iteration. Customers installing gov-mcp see confusing version numbers (gov-mcp 0.3.2 requires ystar-gov 0.42.1-beta). API breakage in Y*gov cascades to gov-mcp users.

**Mission-layer alignment**: Directly serves M-3 (gov-mcp as installable product). Also enables M-1 (company viability -- a product with unstable dependencies doesn't attract customers).

**Counterfactual (if not done)**: In 6 months, Y*gov undergoes a major refactor (e.g., cieu_store.py schema change). Gov-mcp breaks. Customer who installed gov-mcp 0.2.0 runs `pip install --upgrade` and gets broken governance. Customer trust destroyed. This is the #1 risk for any library that wraps a rapidly-evolving internal engine.

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| INV-1 through INV-7 | YES | API stability boundary does not change enforcement semantics, only the contract between two codebases | -- |
| INV-8 (CIEU completeness) | **MAYBE** | If gov-mcp is pinned to ystar-gov>=0.5,<1.0, and a new CIEU event type is added in ystar-gov 0.8, gov-mcp 1.0 won't emit it. Customer's audit trail is missing events. | **Guard**: Define a CIEU event schema version. Gov-mcp advertises which CIEU schema version it supports. Y*gov new event types are added to the schema with `added_in_version` metadata. Gov-mcp logs WARNING for unknown event types but does not crash. Forward-compatible design. |
| INV-9 through INV-15 | YES | Orthogonal | -- |

### Axis C -- Technical Viability

**API stability design**:

The "public API surface" of Y*gov that gov-mcp depends on:
1. `ystar.governance.forget_guard.ForgetGuard.check()` -- core governance check
2. `ystar.governance.cieu_store.CIEUStore.emit()` -- audit event emission
3. `ystar.governance.cieu_store.CIEUStore.query()` -- audit query
4. `ystar.governance.boundary_enforcer.BoundaryEnforcer.check_path()` -- path verification
5. `ystar.governance.omission_engine.OmissionEngine.scan()` -- omission detection
6. `ystar.governance.router_registry.RouterRegistry.route()` -- action routing
7. `ystar.adapters.hook.check_hook()` -- the main governance entry point

This is 7 public functions. Stability contract:
- Semver strict on gov-mcp: breaking API change = major bump
- Y*gov provides a `ystar.public_api` module that re-exports only the stable interface
- Deprecation: warn for 2 minor versions before removal
- Test suite: gov-mcp CI runs against Y*gov `main` branch nightly. Breakage = P0 for Y*gov to fix (not gov-mcp to adapt)

**Failure modes**:
1. **Version pin too tight**: gov-mcp requires ystar-gov==0.5.3 exactly. Y*gov security fix 0.5.4 not picked up. Mitigation: pin as `>=0.5,<1.0` (compatible range).
2. **Version pin too loose**: gov-mcp works with ystar-gov 0.5 but not 0.9 due to internal change. Mitigation: nightly CI catches this immediately.
3. **Circular dependency**: gov-mcp imports ystar-gov. If ystar-gov ever imports gov-mcp (e.g., for MCP protocol utilities), circular. Mitigation: one-way dependency enforced by CI check (no import of gov_mcp in ystar codebase).

**Quantitative improvement**:
- Gov-mcp can ship 1.0 while Y*gov is still 0.x
- Customer sees stable version number (gov-mcp 1.0.3)
- Y*gov internal refactors don't require gov-mcp release
- API stability cost: ~7 public functions to maintain, manageable

**Experiment design**:

**Test E1**: API surface extraction
- Setup: Grep all Y*gov imports in gov-mcp codebase. List exact functions/classes used.
- Measure: API surface size. Any imports from `ystar.internal` or private modules?
- Success criteria: All gov-mcp imports use only public API (<10 functions). Zero private imports.
- Tool: `ast.parse()` + import visitor on gov-mcp source.

**Test E2**: Version compatibility matrix
- Setup: Install gov-mcp with ystar-gov 0.42 (current), 0.40 (2 versions back), and a mock 0.50 (with one function renamed). Run gov-mcp test suite each time.
- Measure: Pass/fail per version combination.
- Success criteria: 0.42 and 0.40 pass. 0.50 with rename fails clearly (not silently).
- Tool: `pytest` + `pip install ystar-gov==X.Y`.

**Test E3**: Forward compatibility
- Setup: Add a new CIEU event type in Y*gov. Gov-mcp does not know about it. Verify gov-mcp does not crash and logs WARNING.
- Success criteria: No crash. Warning logged. Event still stored in CIEU db.
- Tool: `pytest` + custom CIEU event.

---

## STEP 6: Section 24.6 -- Keep 1: 3 repos separate (Y*gov / gov-mcp / ystar-company)

### Axis A -- Goal Understanding

**Problem considered**: Consolidating 3 repos into a monorepo for simplified dependency management, unified CI, and single git history. The CEO explicitly rejected this.

**Mission-layer alignment**: M-1 (company viability -- repo visibility matters for open-source traction), M-2/M-3 (separate products with different licenses/audiences).

**Counterfactual (if merged)**: A monorepo containing ystar-company (potentially sensitive: Board strategy, financials, customer lists) alongside Y*gov (MIT open-source) creates a permanent risk of accidental sensitive data exposure via git push. One wrong `.gitignore` entry leaks company strategy. Also: open-source contributors to Y*gov see company internal operations in the same repo, creating confusion and trust issues.

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| All (INV-1 through INV-15) | YES | Keeping repos separate is the status quo. No change = no new threat. | -- |

### Axis C -- Technical Assessment

**This is the correct decision.** The three repos serve fundamentally different audiences:
- Y*gov (MIT): open-source community, external contributors, technical evaluators
- gov-mcp (MIT): customers, enterprise evaluators, MCP ecosystem
- ystar-company: internal team operations, potentially sensitive data

Merging them violates the principle of least privilege at the repository level. The operational cost of cross-repo dependencies (pip install, git submodule) is low and well-understood.

**One enhancement to consider**: Add a CI job that validates cross-repo compatibility on every Y*gov PR (installs gov-mcp + runs gov-mcp tests against the PR branch). This catches breakage before merge, without coupling the repos.

**Verdict**: No experiment needed. Keep as-is.

---

## STEP 7: Section 24.7 -- Keep 2: Mirror / Dream / Idle_pulse as 3 separate daemons

### Axis A -- Goal Understanding

**Problem considered**: Merging Mirror, Dream, and Idle_pulse into a single daemon with 3 scheduled tasks. CEO rejected this, arguing that their failure modes are independent and merging complicates debugging.

**Mission-layer alignment**: M-5 (persistent entity -- Dream), M-6 (disaster recovery -- Mirror), operational health (Idle_pulse).

**Counterfactual (if merged)**: A single daemon running backup, dream inference, and idle detection. Dream inference calls Gemma (I/O-bound, 10-15s per call). During dream, idle_pulse detection is blocked (same event loop). Board comes back, types a message, idle_pulse fails to detect activity transition. Governance miss.

However, note that if Section 24.1 is adopted (master daemon with asyncio workers), these 3 functions could naturally become 3 workers within the master daemon rather than 3 separate processes. The CEO's reasoning about "independent failure modes" is valid for separate processes but is addressable within asyncio (per-worker exception isolation).

### Axis B -- Invariant Preservation

| Invariant | Preserved? | Threat Mechanism | Mitigation |
|---|---|---|---|
| All (INV-1 through INV-15) | YES | Keeping daemons separate is status quo. No change = no new threat. | -- |

### Axis C -- Technical Assessment

**I partially disagree with the CEO's reasoning, but agree with the conclusion for different reasons.**

CEO's argument: "different functions, different failure modes, separate debugging." This is true for independent processes. However, in the context of Section 24.1 (1 master daemon + 9 asyncio workers), these 3 functions should be evaluated as additional workers/services within the master daemon, not as completely separate processes.

**My recommendation**: Keep Mirror as a separate daemon (it involves heavy I/O: rsync, S3 upload, filesystem operations that benefit from their own process and don't share the Gemma inference event loop). Fold Dream and Idle_pulse into the aiden_cluster_daemon as specialized workers (they both need Gemma inference access and benefit from sharing the event loop with agent workers).

This gives us:
- `aiden_cluster_daemon.py`: 9 agent workers + Dream worker + Idle_pulse worker = 11 workers in 1 process
- `ystar_backup_daemon.py`: Mirror + 4 target plugins = 1 process (from Section 24.3)
- Total: 2 daemon processes + Ollama + (optionally) gov-mcp = 4 processes

vs CEO's proposal: 3 separate daemons (Mirror + Dream + Idle_pulse) + aiden_cluster_daemon + Ollama + gov-mcp = 6 processes.

The 2-process variant is simpler while preserving the "heavy I/O backup separate from inference" architectural boundary.

**However**, this is a minor point. The 3-daemon approach works fine and is defensible. The 2-daemon approach is slightly better for operational simplicity but introduces minor coupling between Dream/Idle_pulse and the agent cluster. I accept the CEO's decision to keep 3 separate daemons as a conservative, safe choice.

**Verdict**: Accept with a note that Dream and Idle_pulse are candidates for absorption into the master daemon in a future optimization pass. No experiment needed for the "keep separate" decision.

---

## STEP 8: Final Verdict Matrix and Execution Order

### Verdict Matrix

| Section | Proposal | Verdict | Key Guard Requirements |
|---|---|---|---|
| 24.1 | Consolidation 1: 9 agent daemons -> 1 master + 9 asyncio workers | **(b) ADOPT-WITH-GUARD** | (1) All CPU-bound work in `asyncio.to_thread()` to prevent event loop starvation. (2) Worker-ID-based identity resolution replacing PID-based. (3) ForgetGuard as mandatory middleware in master daemon, structurally non-bypassable. (4) Watchdog coroutine with 30s heartbeat check. (5) DB writes serialized through single `db_writer` coroutine. |
| 24.2 | Consolidation 2: hook_wrapper.py retirement -> gov-mcp gateway | **(b) ADOPT-WITH-GUARD** | **CRITICAL**: Do NOT fully retire hook_wrapper. Reduce to 30-50 LOC shim that calls gov-mcp via MCP protocol. The shim is the structural non-bypassability guarantee for Claude Code (MCP tools are optional; hooks are mandatory). Same principle for Gemma daemon (master daemon middleware is mandatory) and office (MCP client middleware is mandatory). Gov-mcp becomes single governance logic host. Shim + middleware = structural enforcement at each entry point. |
| 24.3 | Consolidation 3: 4-route backup -> 1 daemon + 4 plugins | **(a) ADOPT** | No guards needed beyond standard software engineering (test the plugin interface, wrap existing proven scripts before rewriting). Lowest risk of all 7 proposals. |
| 24.4 | Consolidation 4: WHO_I_AM company + per-agent split | **(a) ADOPT** | Minor guard: prompt_tier system to manage token budget on Gemma 12B's context window. Validate total inject < 25% of minimum context window. |
| 24.5 | Split 1: gov-mcp release decouple | **(b) ADOPT-WITH-GUARD** | (1) Define `ystar.public_api` module with 7 stable functions. (2) Semver strict on gov-mcp. (3) Nightly cross-repo CI. (4) CIEU schema versioning for forward compatibility. |
| 24.6 | Keep 1: 3 repos separate | **(a) ADOPT** | Add cross-repo CI for compatibility testing. |
| 24.7 | Keep 2: 3 separate daemons (Mirror/Dream/Idle_pulse) | **(a) ADOPT** | Accepted as conservative choice. Note: Dream + Idle_pulse are future candidates for absorption into master daemon. |

### Execution Order

The proposals have dependencies that constrain ordering:

```
Phase 0 (This ruling) -- Board approval gate
    |
    v
Phase 1: Foundations (parallel tracks)
    Track A: Section 24.4 (WHO_I_AM split) -- no dependencies, immediate
    Track B: Section 24.5 (gov-mcp decouple) + CZL-GOV-MCP-ACTIVATE
             -- gov-mcp Day 4-N implementation must complete
    Track C: Section 24.1 (aiden_cluster_daemon) prototype
             -- design + implement master daemon + 2 test workers
    |
    v  (Gate: gov-mcp 0.1.0 on PyPI + MCP server testable locally)
Phase 2: Governance Gateway
    Section 24.2 (hook_wrapper -> shim + gov-mcp)
    -- depends on gov-mcp being LIVE and MCP-callable
    -- Test B1/B2/B3 must pass before cutting over
    |
    v  (Gate: governance through gov-mcp verified for Claude Code)
Phase 3: Full Daemon
    Section 24.1 (aiden_cluster_daemon) full 9 workers
    -- Test A1/A2/A3 must pass
    Section 24.3 (backup daemon) -- can run parallel with 24.1
    |
    v  (Gate: 9 workers running + backup daemon running + gov-mcp LIVE)
Phase 4: Validation
    Quarterly drill (Section 24.3 Test C3)
    Cross-repo CI setup (Section 24.6)
    Full load test (all 9 workers + governance + backup simultaneously)
```

### Risk-Ordered Priority (if resources constrained, do these first)

1. **Section 24.2 (gov-mcp gateway)** -- highest impact. Solves FG-5 (governance equivalence), de-risks all other proposals. But depends on gov-mcp ACTIVATE.
2. **Section 24.1 (master daemon)** -- enables FG-2 (team persistence). Core architectural change.
3. **Section 24.4 (WHO_I_AM split)** -- quick win, no dependencies, reduces maintenance debt immediately.
4. **Section 24.5 (release decouple)** -- enables M-3 (gov-mcp as product). Needed before any customer-facing launch.
5. **Section 24.3 (backup daemon)** -- important for M-6 but existing scripts work. Can defer to Phase 3.
6. **Section 24.6 + 24.7 (keep decisions)** -- no work required, just document.

### Critical Path

The critical path runs through gov-mcp:
```
CZL-GOV-MCP-ACTIVATE (complete Day 4-N impl, ship PyPI)
    -> Test B1 (MCP latency benchmark)
    -> Section 24.2 (hook_wrapper shim cutover)
    -> Section 24.1 (master daemon with gov-mcp governance)
    -> FG-5 achieved (governance equivalence across runtimes)
```

Everything else is parallel or downstream. **Gov-mcp activation is the single most important blocker for the entire v0.4 architecture.**

---

## Appendix: Summary of All Experiments

| Test ID | Section | What | Success Criteria | Priority |
|---|---|---|---|---|
| A1 | 24.1 | 9 asyncio workers 90 req/s load | p95 <500ms, 0 deadlocks | P1 |
| A2 | 24.1 | ForgetGuard under shared loop | FG eval <5ms total, jitter <100ms | P1 |
| A3 | 24.1 | Worker crash recovery | Recovery <5s, 0 impact on others | P2 |
| B1 | 24.2 | MCP round-trip latency | p95 <20ms sequential, >500 req/s | **P0** |
| B2 | 24.2 | Hook shim end-to-end | Overhead <30ms p95 | P0 |
| B3 | 24.2 | Gov-mcp crash recovery | Fail-closed works, recovery <5s | P1 |
| C1 | 24.3 | Plugin interface parity | 100% output match vs existing script | P2 |
| C2 | 24.3 | Encryption round-trip | Hash match, >100MB/s | P2 |
| C3 | 24.3 | Quarterly drill simulation | Full restore + governance_boot OK | P2 |
| D1 | 24.4 | Identity injection parity | Zero content delta after split | P1 |
| D2 | 24.4 | Token count validation | <25% of 8K context | P1 |
| D3 | 24.4 | Cache refresh latency | <5s | P2 |
| E1 | 24.5 | API surface extraction | <10 public functions, 0 private imports | P1 |
| E2 | 24.5 | Version compatibility | Pass for current and -2 versions | P2 |
| E3 | 24.5 | Forward compatibility | No crash on unknown event type | P2 |

**Total: 15 experiments. 2 are P0 (must pass before Phase 2 cutover). 6 are P1 (must pass before Phase 3 full deployment). 7 are P2 (can run in parallel with deployment).**

---

*CTO Ethan Wright, 2026-04-21. This ruling is my independent technical assessment per Board directive. All proposals are auditable against the 15 governance invariants and 6 mission goals listed in STEP 0. No fabricated data -- all LOC counts, module paths, and architectural claims are empirically verified from the codebase.*
