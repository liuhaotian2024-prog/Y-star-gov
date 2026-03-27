# Y*gov — Runtime Governance Framework for Multi-Agent AI Systems

**v0.41.1 · MIT License · Y* Bridge Labs**

Multi-agent AI systems have a governance gap. Y*gov closes it with deterministic runtime enforcement, obligation tracking, and tamper-evident audit chains.

---

## Quick Start

**Install:**

```bash
pip install ystar
```

**Requirements:** Python >= 3.11

**Three-step integration (Claude Code / OpenClaw):**

```bash
# 1. Initialize session config
ystar setup

# 2. Install governance hook
ystar hook-install

# 3. Create AGENTS.md in your project root with your rules
```

**Example AGENTS.md:**

```markdown
# Governance Rules

- Never modify /production
- Never run rm -rf
- Only write to ./workspace/
- Maximum $10,000 per transaction
- Complete all assigned tasks within 10 minutes
```

**Verify installation:**

```bash
ystar doctor
```

All 7 checks should pass. If any fail, run `ystar doctor` again to see diagnostic details.

---

## What Y*gov Does

Three capabilities, all deterministic:

### 1. Permission Enforcement at Execution Time

Every tool call any agent makes is intercepted before execution and checked against your governance contract. ALLOW or DENY is computed deterministically — no LLM in the enforcement path. Mean latency: 0.042ms.

### 2. Obligation Tracking with Automatic Enforcement

When a task is assigned, an obligation record is created with a deadline. If the agent misses the deadline, the next tool call it makes triggers detection. The agent is blocked from unrelated work until the obligation is fulfilled. No external polling. No cron jobs.

### 3. Tamper-Evident CIEU Audit Chain

Every decision (ALLOW or DENY, with full context) is written to a SHA-256 Merkle-chained SQLite database. Records cannot be modified after creation. Any tampering breaks the hash chain, detectable by `ystar verify`.

---

## Integration Paths

### Claude Code (Recommended)

Y*gov integrates as a `PreToolUse` hook — the native Claude Code extension point that fires before every tool call.

**Install the hook:**

```bash
ystar hook-install
```

This registers Y*gov in `~/.claude/settings.json`. Every subagent spawned by Claude Code is governed by the same hook. No per-agent configuration.

**What the hook does:**

```
Agent → tool call → PreToolUse fires → Y*gov check() → ALLOW / DENY
                                                ↓
                                       CIEU record written
                                       Obligations scanned
                                       Delegation chain verified
```

**Verified working on:** macOS, Linux, Windows (Git Bash).

### OpenClaw / Multi-Agent Frameworks

Y*gov ships a first-class OpenClaw adapter at `ystar.domains.openclaw`.

```python
from ystar.domains.openclaw import OpenClawDomainPack, make_openclaw_chain
from ystar.domains.openclaw.adapter import make_session, enforce, OpenClawEvent, EventType

# Create domain pack with role-based contracts
pack = OpenClawDomainPack(
    workspace_root="./workspace",
    doc_domains=["docs.python.org", "github.com"]
)

# Build delegation chain: planner -> coder -> tester
chain = make_openclaw_chain(
    pack=pack,
    allowed_paths=["./src", "./tests"],
    allowed_domains=None,  # restrict external access
    include_release=False
)

# Create session state
session = make_session(
    session_id="demo_session",
    allowed_paths=["./src"],
    pack=pack,
    chain=chain,
    strict=False  # set True for production
)

# Enforce governance on events
event = OpenClawEvent(
    event_type=EventType.FILE_WRITE,
    agent_id="coder_agent",
    session_id="demo_session",
    file_path="./src/main.py",
    patch_summary="Fix null pointer bug",
    task_ticket_id="TASK-001"
)

decision, cieu_records = enforce(event, session)
# decision: EnforceDecision.ALLOW / DENY / ESCALATE
# cieu_records: List[OpenClawCIEU] with full audit trail
```

**Core OpenClaw functions:**

- `OpenClawDomainPack`: 6 role contracts (planner, coder, tester, reviewer, researcher, release)
- `make_openclaw_chain()`: builds delegation chain with monotonicity guarantees
- `make_session()`: creates SessionState with delegation chain
- `enforce()`: main governance entry point (ALLOW/DENY/ESCALATE)

**Test coverage:** 55 passing tests, 979 lines of test code covering all 6 role contracts, delegation chain verification, and CIEU record generation.

### Python API (Direct Integration)

Use Y*gov's core API directly in any Python application:

```python
from ystar import Policy, check, IntentContract

# Define a contract
contract = IntentContract(
    deny=[".env", "/etc/"],
    only_paths=["./projects/"],
    deny_commands=["rm -rf", "sudo"],
    invariant=["amount > 0", "amount < 1000000"]
)

# Check a proposed action
result = check(
    params={"file_path": "./projects/data.txt", "amount": 500},
    output={},
    contract=contract
)

if result.passed:
    print("ALLOW")
else:
    for violation in result.violations:
        print(f"DENY: {violation.message}")
```

**Available imports:**

```python
from ystar import (
    # Core types
    IntentContract, Policy, check, CheckResult, enforce,

    # Omission governance
    OmissionEngine, ObligationRecord, TrackedEntity,

    # Delegation
    DelegationChain, DelegationContract,

    # OpenClaw
    from ystar.domains.openclaw import OpenClawDomainPack, make_openclaw_chain
)
```

---

## CLI Reference

```bash
ystar setup [--yes]
    Initialize .ystar_session.json in current directory.

ystar hook-install
    Register PreToolUse hook in ~/.claude/settings.json.
    Idempotent. Safe to run multiple times.

ystar init
    Interactive wizard: translates AGENTS.md to IntentContract.
    Uses LLM (if ANTHROPIC_API_KEY set) or regex fallback.

ystar doctor
    7-point health check. Exit 0 = healthy, 1 = issues found.
    Checks: session config, hook registration, CIEU database,
            AGENTS.md, hook self-test.

ystar report [--db <path>] [--format text|json]
    CIEU summary: total decisions, deny rate, by-agent breakdown.

ystar verify [--session <id>] [--db <path>]
    Verify SHA-256 Merkle chain integrity.

ystar seal [--session <id>]
    Write Merkle root. Session becomes immutable.

ystar audit
    Causal audit report: shows what happened and why.

ystar simulate
    A/B comparison: evaluate governance impact on cost/time.

ystar quality
    Contract quality metrics: coverage, false positive rate.

ystar policy-builder
    Launch local HTML policy builder (port 7921).

ystar version
    Print version.
```

---

## Core Data Structures

### IntentContract

```python
@dataclass
class IntentContract:
    name:               str   = ""
    deny:               List[str] = []  # forbidden substrings in any param
    only_paths:         List[str] = []  # file_path whitelist (prefix match)
    deny_commands:      List[str] = []  # forbidden command prefixes
    only_domains:       List[str] = []  # url domain whitelist
    invariant:          List[str] = []  # boolean expressions (AST-safe eval)
    optional_invariant: List[str] = []  # conditional invariants
    value_range:        Dict[str, Dict] = {}  # {"param": {"min": N, "max": M}}
    obligation_timing:  Dict[str, Any]  = {}  # {"task_completion": 600}
    postcondition:      List[str] = []  # post-execution assertions
    hash:               str   = ""      # SHA-256 of source AGENTS.md
```

**Evaluation order:** deny → deny_commands → only_domains → only_paths → value_range → invariant → optional_invariant. Short-circuit on first violation.

### CIEU Record

Every enforcement decision is written to the CIEU database (`cieu_events` table):

| Column | Description |
|--------|-------------|
| seq_global | Monotonic global sequence number |
| event_id | UUID |
| agent_id | Agent that made the call |
| event_type | Tool name (Read, Write, Bash, Agent...) |
| decision | allow / deny |
| violations | JSON array: [{dimension, message}] |
| contract_hash | SHA-256 of governing IntentContract |
| file_path / command / url | Extracted params |
| prev_hash | SHA-256 of previous record |
| record_hash | SHA-256 of this record |
| created_at | Epoch timestamp (immutable) |

---

## Differentiation

### vs. LangSmith / Langfuse / Arize

These are observability tools. They record what happened. They are cameras.

Y*gov is enforcement. It determines what is allowed to happen. It is a gate.

You need both. Y*gov does not replace observability — it adds the enforcement layer that observability cannot provide.

### vs. Guardrails AI

Guardrails validates LLM inputs and outputs. It sits at the model API boundary.

Y*gov sits at the tool execution boundary. Multi-agent governance requires tool-level enforcement, delegation chain verification, and obligation tracking — none of which are in scope for Guardrails.

### vs. Claude Code Auto Mode

Auto Mode uses an internal classifier. Its rules are not inspectable. Its decisions are not auditable.

Y*gov uses **your** rules, written in plain English in `AGENTS.md`, enforced deterministically, with every decision written to a tamper-evident audit chain you own and control.

For personal projects: Auto Mode is fine.
For anything subject to SOC 2, HIPAA, FINRA, FDA 21 CFR Part 11, or any enterprise audit requirement: you need Y*gov.

---

## Technical Innovations

### 1. Action-Triggered Passive Non-Compliance Detection (US Provisional Patent P4)

The canonical approach to obligation tracking requires external polling (cron jobs). Y*gov's `OmissionEngine` uses a fundamentally different architecture: **the agent's own next tool call is the detection trigger**. Every call to `enforce()` internally scans pending obligations. Detection is causally linked to agent behavior, runs in the agent's execution context, and requires no external infrastructure.

### 2. Self-Referential Governance Closure (Patent P3 — SRGCS)

The quis custodiet problem: who governs the meta-governance agent?

Y*gov resolves this by deriving the meta-agent's behavioral constraints from the outputs of the same governance system it is improving. The governance system governs itself without requiring a separate authority layer.

### 3. DelegationChain Monotonicity Verification

Y*gov formalizes and enforces the monotonic authority property:

```
∀ (parent P, child C) in delegation chain:
  C.deny ⊇ P.deny
  C.deny_commands ⊇ P.deny_commands
  C.only_paths ⊆ P.only_paths
  C.only_domains ⊆ P.only_domains
```

`DelegationChain.validate()` checks this on every `SUBAGENT_SPAWN` and `HANDOFF` event. Violations are written to the CIEU chain and block the spawn.

### 4. Constitutional Hash Traceability

Every `IntentContract` carries the SHA-256 hash of the `AGENTS.md` document that produced it. Every CIEU record carries the contract hash. This creates complete traceability:

```
AGENTS.md → contract_hash → IntentContract → CIEU record
```

Auditors can verify that any specific enforcement decision derived from a specific version of the governance document.

---

## Performance

Single thread, Python 3.11, M2 MacBook Pro:

| Operation | Mean | p99 |
|-----------|------|-----|
| `check()` ALLOW | 0.042ms | 0.080ms |
| `check()` DENY | 0.041ms | 0.065ms |
| `enforce()` full pipeline | 0.021ms | 0.055ms |
| `OmissionEngine.scan()` 20 obligations | 0.011ms | 0.018ms |

Industry reference (Microsoft AGT): < 0.1ms.
Y*gov `check()` at 0.042ms mean: **2.4× faster.**

CIEU write throughput: ~8,000 records/second (SQLite WAL).

---

## Patent Portfolio

**P1 — US Provisional 63/981,777** (January 2026)
CIEU five-tuple structure, SHA-256 Merkle chain, DelegationChain monotonicity, session sealing.

**P3 — SRGCS** · US Provisional 64/017,557 (March 26, 2026)
Self-referential governance closure: meta-governance agent constrained by contracts derived from its own governance outputs.

**P4 — Action-Triggered Passive Non-Compliance Detection** · US Provisional 64/017,497 (March 26, 2026)
Obligation expiry detection triggered by agent's own subsequent tool invocations; two-phase SOFT/HARD enforcement with automatic gate release.

---

## License

MIT. Free for commercial use, internal deployment, academic research, OEM embedding.

---

## Contact

**Haotian Liu · Y* Bridge Labs**
liuhaotian2024@gmail.com

Enterprise licensing · Domain pack development · Research collaboration

---

## Troubleshooting

**Installation fails:**
- Ensure Python >= 3.11: `python --version`
- Upgrade pip: `pip install --upgrade pip`
- Install from source: `git clone https://github.com/liuhaotian2024-prog/Y-star-gov && cd Y-star-gov && pip install -e .`

**`ystar doctor` reports issues:**
- Run `ystar setup` to create `.ystar_session.json`
- Run `ystar hook-install` to register the hook
- Create `AGENTS.md` in your project root

**Hook not firing:**
- Verify hook is registered: `cat ~/.claude/settings.json | grep ystar`
- Restart Claude Code
- Check hook logs in `~/.ystar/hook.log`

**Tests failing:**
- Run tests: `python -m pytest tests/ -v`
- Expected: 141/141 passing
- Report failures to: liuhaotian2024@gmail.com

---

## Repository

**Source:** https://github.com/liuhaotian2024-prog/Y-star-gov
**Issues:** https://github.com/liuhaotian2024-prog/Y-star-gov/issues
**Docs:** https://ystar-gov.com (coming soon)

