# Y*gov — Runtime Governance Framework for Multi-Agent AI Systems

**v0.41.1 · MIT License · Y* Bridge Labs**

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Core Data Structures](#core-data-structures)
3. [Enforcement Engine](#enforcement-engine)
4. [CIEU Audit Chain](#cieu-audit-chain)
5. [OmissionEngine — Obligation Tracking](#omissionengine)
6. [DelegationChain — Monotonic Authority](#delegationchain)
7. [Hook Lifecycle](#hook-lifecycle)
8. [Natural Language to Contract](#natural-language-to-contract)
9. [Path A — Self-Referential Meta-Governance (SRGCS)](#path-a-srgcs)
10. [CLI Reference](#cli-reference)
11. [Performance](#performance)
12. [Patents](#patents)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Claude Code Runtime                       │
│                                                                  │
│  Agent → Tool Call → PreToolUse Hook → Y*gov check()            │
│                              │                                   │
│                    ┌─────────▼──────────┐                        │
│                    │   Y*gov Kernel     │                        │
│                    │                    │                        │
│                    │  IntentContract    │                        │
│                    │  ← AGENTS.md       │                        │
│                    │    (via LLM/regex) │                        │
│                    │                    │                        │
│                    │  check(params,     │                        │
│                    │        contract)   │                        │
│                    │                    │                        │
│                    │  ALLOW / DENY      │                        │
│                    └─────────┬──────────┘                        │
│                              │                                   │
│              ┌───────────────┼───────────────┐                  │
│              ▼               ▼               ▼                  │
│       CIEU Store      OmissionEngine   DelegationChain          │
│    (audit chain)    (obligation SLA)  (monotonicity)            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                    Path A (Meta-Governance)                      │
│                                                                  │
│  GovernanceLoop → GovernanceSuggestion                          │
│       │                    │                                     │
│       │         suggestion_to_contract()                         │
│       │                    │                                     │
│       └────────► IntentContract (governs Path A itself)          │
│                    │                                             │
│                  check() ← same kernel as operational agents     │
└─────────────────────────────────────────────────────────────────┘
```

**Package structure:**

```
ystar/
├── kernel/
│   ├── dimensions.py      # IntentContract, DelegationChain, CallRecord
│   ├── engine.py          # check() — the enforcement core
│   ├── nl_to_contract.py  # Natural language → IntentContract
│   └── prefill.py         # Regex-based constraint extraction
├── adapters/
│   ├── hook.py            # Claude Code PreToolUse integration
│   └── omission_adapter.py
├── governance/
│   ├── cieu_store.py      # Append-only audit database
│   ├── omission_engine.py # Two-phase obligation enforcement
│   ├── governance_loop.py # Health observation + suggestions
│   └── ...
├── module_graph/
│   └── meta_agent.py      # Path A SRGCS implementation
└── _cli.py                # CLI entry points
```

---

## Core Data Structures

### IntentContract

Defined in `ystar/kernel/dimensions.py`. Specifies behavioral boundaries for a single agent or session.

```python
@dataclass
class IntentContract:
    name:               str   = ""
    
    # Path-based access control
    deny:               List[str] = field(default_factory=list)
    # Strings that must NOT appear in file_path, url, or command params.
    # Substring match (not glob). Applied before only_paths whitelist.
    # Example: ["/etc", "/production", ".env"]
    
    only_paths:         List[str] = field(default_factory=list)
    # If non-empty: file_path must start with one of these prefixes.
    # Empty = no path restriction (allow all paths not in deny).
    
    deny_commands:      List[str] = field(default_factory=list)
    # Command prefixes that are absolutely forbidden.
    # Matched against the 'command' parameter.
    # Example: ["rm -rf", "sudo", "DROP TABLE"]
    
    only_domains:       List[str] = field(default_factory=list)
    # If non-empty: url must be under one of these domains.
    
    invariant:          List[str] = field(default_factory=list)
    # Python boolean expressions evaluated against action params.
    # All must be True for the action to be allowed.
    # Example: ["amount > 0", "risk_approved == True"]
    
    optional_invariant: List[str] = field(default_factory=list)
    # Evaluated only when the referenced variable exists in params.
    
    value_range:        Dict[str, Dict] = field(default_factory=dict)
    # Numeric bounds: {"param_name": {"min": N, "max": M}}
    
    obligation_timing:  Dict[str, Any] = field(default_factory=dict)
    # SLA deadlines: {"task_completion": 600, "acknowledgement": 60}
    # Units: seconds
    
    postcondition:      List[str] = field(default_factory=list)
    # Boolean expressions evaluated after action completes.
    
    hash:               str   = ""
    # SHA-256 of the source document (AGENTS.md) that produced this contract.
    # Used for constitutional traceability in Path A.
```

**Evaluation semantics:** `deny` takes precedence over `only_paths`. All active dimensions must pass for ALLOW. First failing dimension produces DENY with specific reason.

---

### CheckResult

Returned by `check()`:

```python
@dataclass
class CheckResult:
    passed:     bool
    violations: List[Violation]  # empty if passed
    contract:   Optional[IntentContract]
    params:     Dict[str, Any]   # normalized input params
```

### CallRecord (CIEU Five-Tuple)

Written to the audit chain on every `check()` call:

```python
@dataclass  
class CallRecord:
    session_id:     str    # session or project identifier
    agent_id:       str    # agent that made the call
    action:         str    # tool name (Read, Write, Bash, etc.)
    params:         dict   # sanitized action parameters
    result:         dict   # {decision: allow/deny, violations: [...]}
    contract_hash:  str    # SHA-256 of governing IntentContract
    ts:             float  # epoch timestamp (immutable after write)
```

---

## Enforcement Engine

`check()` in `ystar/kernel/engine.py`.

**Evaluation order (short-circuit on first violation):**

1. `deny` — substring scan of all string params
2. `deny_commands` — prefix match on `command` param  
3. `only_domains` — domain suffix match on `url` param
4. `only_paths` — prefix match on `file_path` param
5. `value_range` — numeric bounds check on specified params
6. `invariant` — safe Python expression evaluation (whitelist sandbox)
7. `optional_invariant` — conditional invariant (skipped if var absent)
8. `postcondition` — evaluated post-execution (advisory, not blocking)

**Security hardening (FIX-1 through FIX-4):**

- `_safe_eval()` uses AST whitelist — only literals, comparisons, boolean ops
- No `exec`, `eval`, `import`, attribute access, or function calls in invariants
- param normalization prevents injection via alias keys
- Contract hash verification in Path A detects tampering

**Signature:**

```python
def check(
    params:   Dict[str, Any],
    state:    Dict[str, Any],
    contract: Optional[IntentContract] = None,
) -> CheckResult
```

---

## CIEU Audit Chain

`ystar/governance/cieu_store.py`

SQLite-backed, append-only. Each record contains a `prev_hash` field linking to the SHA-256 of the previous record, forming a Merkle chain.

**Schema (cieu_events table):**

| Column | Type | Description |
|--------|------|-------------|
| seq_global | INTEGER | Monotonic global sequence |
| event_id | TEXT | UUID |
| session_id | TEXT | |
| agent_id | TEXT | |
| event_type | TEXT | Tool name (Read, Write, Bash...) |
| decision | TEXT | allow / deny |
| passed | INTEGER | 1 = allowed |
| violations | TEXT | JSON array of violation objects |
| contract_hash | TEXT | SHA-256 of governing contract |
| file_path | TEXT | Extracted from params |
| command | TEXT | Extracted from params |
| url | TEXT | Extracted from params |
| prev_hash | TEXT | SHA-256 of previous record |
| record_hash | TEXT | SHA-256 of this record |
| created_at | REAL | Epoch timestamp |

**Chain integrity verification:**

```bash
ystar verify --session <session_id>
```

Recomputes all hashes and verifies the chain has not been tampered with.

**Sealing:**

```bash
ystar seal --session <session_id>
```

Writes a Merkle root record marking the session as sealed. Sealed sessions cannot be amended.

---

## OmissionEngine

`ystar/governance/omission_engine.py`

Detects passive non-compliance: obligations that were created but not fulfilled by their deadline.

**Key innovation:** Detection is triggered by the agent's own next tool invocation — no external polling or cron required. When `enforce()` is called (on every tool call), `_auto_feed_omission()` invokes `scan()` internally.

**ObligationRecord fields:**

```python
obligation_id:         str    # UUID
entity_id:             str    # agent or entity obligated  
actor_id:              str    # specific agent
obligation_type:       str    # semantic type
required_event_types:  List[str]  # events that constitute fulfillment
due_at:                float  # absolute epoch deadline
hard_overdue_secs:     float  # seconds after due_at before HARD phase
status:                ObligationStatus
severity:              Severity  # LOW / MEDIUM / HIGH / CRITICAL
soft_count:            int    # number of SOFT cycles elapsed
```

**Two-phase state machine:**

```
PENDING
    │
    │  now >= due_at
    ▼
SOFT_OVERDUE ──────────────────────────────────────────────────────┐
    │                                                               │
    │  now >= due_at + hard_overdue_secs                           │
    ▼                                                               │
HARD_OVERDUE                                              FULFILLED ◄─┘
    │                                                       ▲
    │  INTERRUPT_GATE active: tool calls DENIED             │
    │  except required_event_types                          │
    └──────────────────────────────────────────────────────►┘
         agent produces required_event_type → gate clears
```

**SOFT_OVERDUE:** Warning attached to tool call response. Call proceeds. `soft_count` increments. Severity escalates at thresholds (soft_count ≥ 2 → MEDIUM, ≥ 3 → HIGH).

**HARD_OVERDUE:** `InterventionEngine` produces INTERRUPT_GATE pulse. Subsequent tool calls denied unless `event_type ∈ required_event_types`. Gate clears automatically when obligation is fulfilled — no manual intervention needed.

---

## DelegationChain

`ystar/kernel/dimensions.py`

Enforces the monotonic authority property across multi-agent hierarchies.

**Formal property:**

For any parent contract `P` and child contract `C` in a delegation chain:

```
C.deny ⊇ P.deny
C.deny_commands ⊇ P.deny_commands  
C.only_paths ⊆ P.only_paths  (whitelist shrinks, never grows)
C.only_domains ⊆ P.only_domains
```

A child agent can never be granted permissions exceeding its parent. This prevents privilege escalation through subagent spawning.

**Verification:**

```python
chain = DelegationChain(contracts=[parent_contract, child_contract])
result = chain.validate()
# result.valid: bool
# result.violations: List[str]  — specific monotonicity violations
```

**Integration:** Verified automatically on every SUBAGENT_SPAWN or HANDOFF event in the hook adapter.

---

## Hook Lifecycle

`ystar/adapters/hook.py`

Registered as a Claude Code `PreToolUse` hook. Executes before every tool call.

**Execution sequence:**

```
Claude Code emits tool call
    │
    ▼
hook command (in settings.json):
  MSYS_NO_PATHCONV=1 python -c "
    payload = json.loads(sys.stdin.read())  # {tool_name, tool_input, agent_id, ...}
    policy = Policy.from_agents_md('AGENTS.md', confirm=False)
    result = check_hook(payload, policy)
    print(json.dumps(result))
  "
    │
    ▼
check_hook(payload, policy):
    1. extract_params(payload)       # normalize tool_input → flat params dict
    2. resolve_effective_contract()  # look up agent's contract from policy
    3. check(params, {}, contract)   # enforce IntentContract
    4. _auto_feed_omission(event)    # scan pending obligations
    5. gate_check(actor_id)          # check INTERRUPT_GATE (HARD_OVERDUE)
    6. write_cieu(result)            # append to audit chain
    7. return {action: allow/block, message: str}
    │
    ▼
Claude Code reads stdout:
  {} or {"action": "allow"}  → tool call proceeds
  {"action": "block", "message": "..."}  → tool call denied
```

**Settings.json format (Windows-compatible):**

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "",
      "hooks": [{
        "type": "command",
        "command": "MSYS_NO_PATHCONV=1 C:/Users/.../python.exe -c \"...\""
      }]
    }]
  }
}
```

Note: Forward slashes in Python path (`C:/Users/...`) prevent MSYS path mangling in Git Bash on Windows (v0.41.1 fix).

---

## Natural Language to Contract

`ystar/kernel/nl_to_contract.py`

Translates `AGENTS.md` (plain English governance rules) into an `IntentContract`.

**Pipeline:**

```
AGENTS.md text
    │
    ▼
translate_to_contract(text)
    │
    ├─► _try_llm_translation(text)
    │       │
    │       ├─ Requires ANTHROPIC_API_KEY env var
    │       ├─ Model: claude-sonnet-4-20250514
    │       ├─ Structured JSON output (valid IntentContract fields only)
    │       ├─ validate_contract_draft() — deterministic quality check
    │       │     checks: invariant syntax, value_range direction,
    │       │             command truncation, coverage rate
    │       └─ Returns (contract_dict, "llm", 0.90)
    │
    └─► _try_regex_translation(text)   ← fallback if LLM unavailable
            │
            ├─ Constitutional rules: [deontic operator] × [semantic domain]
            │    "never access /etc" → deny: ["/etc"]
            │    "never run rm" → deny_commands: ["rm"]
            │    "only write to ./src/" → only_paths: ["./src/"]
            └─ Returns (contract_dict, "regex", 0.50)
```

**confirm=False required in hook context** (stdin is JSON payload, not terminal).

**Supported AGENTS.md patterns (regex fallback):**

| Pattern | Maps to |
|---------|---------|
| `never access <path>` | `deny` |
| `never run <cmd>` | `deny_commands` |
| `only write to <path>` | `only_paths` |
| `only connect to <domain>` | `only_domains` |

---

## Path A — SRGCS

`ystar/module_graph/meta_agent.py`

**Self-Referential Governance Closure System** (US Provisional Patent P3).

Resolves the quis custodiet problem: the meta-governance agent (Path A) is constrained by contracts derived from the outputs of the governance system it improves.

**Core function:**

```python
def suggestion_to_contract(
    suggestion: GovernanceSuggestion,
    allowed_modules: List[str],
    deadline_secs: float = 600.0,
) -> IntentContract:
```

Maps a `GovernanceSuggestion` (produced by `GovernanceLoop.tighten()`) to an `IntentContract` that governs Path A's own actions during the improvement cycle.

**Mapping (lossy, intentionally):**

```
suggestion.suggested_value  →  contract.obligation_timing["target"]
suggestion.target_rule_id   →  contract.obligation_timing["trigger"]
suggestion.confidence       →  obligation severity weighting
[system safety rules]       →  contract.deny + contract.deny_commands
```

**Lossy by design:** Prevents Path A from gaming the constraint derivation by crafting suggestions that produce permissive contracts.

**Post-condition obligation:** After each improvement action, an `ObligationRecord` is created requiring observable health improvement within `deadline_secs`. Failure triggers HARD_OVERDUE enforcement on Path A itself — same mechanism as operational agents.

**Constitutional hash verification:**

```python
current_hash = sha256(PATH_A_AGENTS.md)
if current_hash != stored_hash:
    cieu_store.write(event_type="constitution_tamper_detected")
    return None  # abort cycle
```

**Closure properties:**

- Path A's constraints are derived from governance system outputs (not external authority)
- Enforcement uses identical `check()` and `PreToolUse` hook as operational agents
- All Path A actions written to the same CIEU chain
- Path A cannot expand its own authority: suggestions are bounded by observed metrics

---

## CLI Reference

```
ystar setup [--yes]
    Generate .ystar_session.json in current directory.
    --yes: use defaults without interactive prompts

ystar hook-install [--config <path>]
    Write PreToolUse hook to ~/.claude/settings.json (or specified path).
    Idempotent: skips if hook already present.

ystar doctor
    Run 7-point environment diagnostic:
    [1] Session Config — .ystar_session.json exists
    [2] Hook Registration — hook found in settings.json
    [3] CIEU Database — accessible, record count
    [4] AGENTS.md — found, contains constraint rules
    [5] Hook Self-Test — /etc/passwd correctly blocked
    Exit 0 if all pass, 1 if any fail.

ystar report [--db <path>] [--format text|json]
    Generate CIEU summary report.
    Default db: .ystar_cieu.db
    Default format: text

ystar verify [--session <id>] [--db <path>]
    Verify SHA-256 Merkle chain integrity.
    Detects any post-write tampering.

ystar seal [--session <id>] [--db <path>]
    Write Merkle root record. Marks session as sealed.

ystar version
    Print version string.

ystar policy-builder
    Launch local HTML policy builder UI (port 7379).
```

---

## Performance

All measurements on single thread, Python 3.11, M2 MacBook Pro.

| Operation | Mean | p99 | Notes |
|-----------|------|-----|-------|
| `check()` ALLOW | 0.042ms | 0.080ms | 5-dim contract |
| `check()` DENY | 0.041ms | 0.065ms | fails on dim 1 |
| `enforce()` full chain | 0.021ms | 0.055ms | includes CIEU write |
| `OmissionEngine.scan()` 20 obligations | 0.011ms | 0.018ms | |
| `gate_check()` | 0.001ms | 0.002ms | |
| `nl_to_contract()` LLM path | ~2000ms | ~5000ms | network-bound |
| `nl_to_contract()` regex path | 0.8ms | 2.1ms | fallback |

**Industry reference:** Microsoft AGT < 0.1ms. Y\*gov `check()` at 0.042ms mean is 2.4× faster.

**At 100 agents × 10 tool calls/second:** `check()` consumes 4.2% CPU on a single core.

**CIEU write throughput:** ~8,000 records/second (SQLite WAL mode, local disk).

---

## Patents

### P1 — US Provisional 63/981,777 (filed January 2026)

Covers:
- CIEU five-tuple causal evidence structure (`CallRecord` schema)
- SHA-256 Merkle chain integrity
- `DelegationChain` monotonicity formal verification
- Session sealing protocol

### P3 — Self-Referential Governance Closure System (SRGCS) (filed March 26, 2026)

Core claim: A method for meta-governance of autonomous AI agent systems wherein the meta-governance agent's behavioral constraints are derived from, validated by, and enforced by the same governance machinery it is responsible for improving — without requiring a separate meta-governance layer.

Key technical mechanism: `suggestion_to_contract()` homomorphic mapping from `GovernanceSuggestion` to `IntentContract`.

### P4 — Action-Triggered Passive Non-Compliance Detection (filed March 26, 2026)

Core claim: A method for detecting obligation expiry in autonomous AI agent systems using the agent's own subsequent tool invocations as the sole detection trigger — no external polling or cron required.

Key technical mechanism: `_auto_feed_omission()` invoked inside `enforce()` on every tool call; two-phase SOFT/HARD enforcement with automatic gate release on fulfillment.

---

## License

MIT — free for commercial use, internal deployment, academic research.

---

## Contact

**Haotian Liu · Y\* Bridge Labs**
liuhaotian2024@gmail.com

Enterprise licensing, domain pack development, research collaboration.
