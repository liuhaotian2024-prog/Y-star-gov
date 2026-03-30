# Y*gov — Runtime Governance Framework for Multi-Agent AI Systems

[![Y*gov governed](https://img.shields.io/badge/governed%20by-Y*gov-brightgreen)](https://github.com/liuhaotian2024-prog/Y-star-gov)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-238%20passing-brightgreen)]()
[![check() latency](https://img.shields.io/badge/check()-0.042ms-blue)]()

**v0.41.1 · MIT License · Y* Bridge Labs**

Zero external dependencies. Installs in seconds. Runs anywhere Python runs.
No supply chain risk. The enforcement layer contains no LLM. Governance cannot be prompt-injected.

**Your AI agents are doing things you don't know about.**

Not because they are malicious — because nothing stops them.

A CTO agent tasked with fixing a bug reads your production credentials. A subagent spawned mid-task inherits full permissions with no constraints. An obligation is assigned, forgotten, and expires silently while the downstream agent waits forever. An agent writes a fabricated audit record as proof of compliance — the check never ran. A child agent quietly receives broader permissions than its parent. A skill named `code-formatter` exfiltrates your data.

None of this is logged. None of it is stopped. You find out later, if at all.

This is not a model quality problem. It is an architectural one. Rules embedded in prompts are suggestions. Y\*gov makes them laws.

Y\*gov is not just a governance tool. It is the execution skeleton that makes your agent team faster, safer, and explainable to regulators — while cutting costs.

### The 4 Reasons Teams Install Y*gov

**1. Your agents access things they should never touch.**
`check()` intercepts every tool call before execution in 0.042ms — no LLM involved, fully deterministic. Path traversal (`../../etc/passwd`), subdomain spoofing, type-confusion bypasses, eval sandbox escapes — four known attack vectors patched at the kernel level. Rules live in code, not prompts. They cannot be overridden by adversarial input or prompt injection.

**2. Your agents are a target — and you cannot see the attack.**
A skill named `code-formatter` exfiltrates your data. A subagent spawned mid-task inherits full permissions. A delegated agent quietly escalates beyond its parent's scope. Y*gov blocks all three: skill risk assessment built on MITRE ATLAS v4.5 (155 techniques, 52 real-world cases) rejects known malicious patterns — `exfil`, `reverse_shell`, `prompt_inject`, `backdoor`, `token_grab` — at install time. `DelegationChain` enforces monotonicity on every spawn: child permissions must be strict subsets of the parent. `NonceLedger` prevents delegation replay attacks.

**3. Your agents will fabricate compliance records if you let them.**
This is not hypothetical. In our controlled experiment (EXP-001), an agent without Y*gov wrote a fabricated CIEU audit record into a public blog post as proof of compliance — the check had never run. Y*gov CIEU records are written by the enforcement engine, not by agents. Every record carries the SHA-256 hash of the previous record. Any tampering breaks the chain. `ystar verify` detects it instantly. Built for SOC 2, HIPAA, FINRA, and FDA 21 CFR Part 11.

**4. Governance makes your agents faster, not slower.**
Our controlled experiment proves the opposite of what most teams expect:

| Metric | Without Y*gov | With Y*gov |
|--------|--------------|------------|
| Tool calls | 117 | 45 (-62%) |
| Token consumption | 186,300 | 156,047 (-16%) |
| Runtime | 9m 19s | 6m 4s (-35%) |
| Unauthorized access | 3 (undetected) | 0 |
| Fabricated audit records | 1 | 0 |

`check()` runs in 0.042ms — 2.4x faster than Microsoft AGT benchmark. Obligation enforcement stopped an agent from looping on a blocked task 66 times. Enforcement is not overhead. It is constrained efficiency.

<details>
<summary>More problems Y*gov solves →</summary>

**5. Agents forget what they promised to do.**
`OmissionEngine` uses action-triggered detection: the agent's own next tool call is the trigger — no polling, no cron jobs. SOFT timeout records a violation. HARD timeout blocks the agent from all unrelated work until the obligation is fulfilled. (US Provisional Patent 64/017,497)

**6. Task goals drift silently during multi-agent handoffs.**
Goal drift detection checks every `SUBAGENT_SPAWN` and `HANDOFF`: does the child task stay within the parent's authorized scope? "Fix a bug" becoming "modify production deployment" or "disable monitoring" triggers ESCALATE and waits for human confirmation.

**7. Your governance rules are invisible to regulators.**
Rules in prompts cannot be audited. Y*gov rules live in `AGENTS.md` — plaintext, version-controlled. Every CIEU record carries the SHA-256 hash of the `AGENTS.md` version that produced it.

</details>

---

## What you will see in 5 minutes

After `ystar hook-install`, trigger a dangerous command in Claude Code:
```
[Y*gov] DENY — /etc is not allowed in command
CIEU record written: seq=1774555489773712
```

`ystar report` output:
```
Y*gov CIEU Report
─────────────────────────────────────
Total decisions : 14
Allow           : 11  (78.6%)
Deny            : 3   (21.4%)
Top blocked     : /etc (2x), rm -rf (1x)
Chain integrity : verified
─────────────────────────────────────
```

`ystar verify` output:
```
Verifying session: my_session
Records: 14
Chain: SHA-256 Merkle chain intact
Result: VALID — audit chain is tamper-evident
```

`ystar doctor` output:
```
Y*gov Doctor — Environment Check
─────────────────────────────────
[1] Session config    OK
[2] Hook registered   OK
[3] CIEU database     OK  14 records
[4] AGENTS.md         OK  3 rules loaded
[5] Hook self-test    OK  /etc/passwd blocked
[6] Chain integrity   OK  verified
[7] Obligations       OK  engine active
─────────────────────────────────
All 7 checks passed
```

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

### The 5 Pain Points Y*gov Solves

| # | Pain Point | Without Y*gov | With Y*gov |
|---|-----------|---------------|------------|
| 1 | Permission violation | Agent accesses any file; discovered after the fact | `check()` blocks before execution in 0.042ms |
| 2 | Obligation forgotten | Task assigned, then lost; no one notices | OmissionEngine two-phase SOFT/HARD enforcement |
| 3 | Audit record fabrication | Agent self-reports compliance; unverifiable | SHA-256 Merkle chain; tampering breaks the hash |
| 4 | Subagent privilege escalation | Child agent inherits or exceeds parent permissions | DelegationChain monotonicity verified at spawn |
| 5 | Governance rules unauditable | Rules buried in prompts; regulators cannot inspect | AGENTS.md plaintext; every decision traces to rule version |

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

**Common issues:**

| Symptom | Cause | Fix |
|---------|-------|-----|
| `enforce()` always returns `DENY` | `agent_id` not recognized | Use exact role names: `coder_agent`, `planner_agent`, `tester_agent`, `reviewer_agent` |
| `enforce()` returns `DENY` on your file | `file_path` outside `allowed_paths` | Set `allowed_paths` to match your project, e.g. `['./my_project']` |
| `enforce()` returns `DENY` with `strict=True` | `task_ticket_id` missing | Add `task_ticket_id='TASK-001'` to `OpenClawEvent`, or use `strict=False` for dev |
| `ystar doctor` shows red checks on fresh install | Session not initialized yet | Run `ystar setup --yes` first, then `ystar hook-install` |

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

## Natural Language → Contract: The Full Flow

Writing governance rules in plain English is how Y*gov is meant to be used. Here is the complete pipeline from a human-readable policy document to an enforced, auditable contract.

### Step 1 — Write your rules in AGENTS.md
```markdown
# AGENTS.md
- Never access /production or /staging environments
- Do not execute trades above $10,000 without risk approval
- Only access: api.stripe.com, api.alpaca.markets
- Never run rm, sudo, or git push --force
- All tasks must complete within 300 seconds
```

### Step 2 — Translate to IntentContract

Y*gov provides two translation paths. The LLM path handles complex, indirect, and context-dependent language. The regex path works offline as a fallback.

**With LLM (recommended):**
```python
import anthropic
from ystar.kernel.nl_to_contract import translate_to_contract

client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY

def llm_call(prompt: str) -> str:
    resp = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.content[0].text

policy = open("AGENTS.md").read()
contract_dict, confidence_label, confidence_score = translate_to_contract(
    policy,
    api_call_fn=llm_call   # omit this argument to use regex fallback
)
# confidence_score: 0.90 (LLM) or 0.50 (regex)
# contract_dict keys: deny, deny_commands, only_domains,
#                     only_paths, value_range, obligation_timing, invariant
```

**Without LLM (regex fallback, no API key required):**
```python
contract_dict, label, score = translate_to_contract(policy)
# score = 0.50 — covers explicit patterns, misses indirect constraints
```

### Step 3 — Quality check before activation

Before any contract is activated, Y*gov runs a deterministic quality check that catches:

- Invariant syntax errors (malformed Python expressions)
- `value_range` direction inversions (`min > max`)
- Missing coverage for high-risk patterns found in the source text
- Conflicting rules
```python
from ystar.kernel.nl_to_contract import validate_contract_draft
from ystar.kernel.dimensions import IntentContract

draft = IntentContract(
    name="my_agent",
    deny=contract_dict.get("deny", []),
    deny_commands=contract_dict.get("deny_commands", []),
    only_domains=contract_dict.get("only_domains", []),
    value_range=contract_dict.get("value_range", {}),
    obligation_timing=contract_dict.get("obligation_timing", {}),
    invariant=contract_dict.get("invariant", []),
)

report = validate_contract_draft(draft, source_text=policy)
# report.issues  — list of problems found
# report.passed  — True if safe to activate
```

### Step 4 — Human confirmation, then activate

The contract does not enforce anything until you explicitly confirm it. This is by design — the LLM translation step is the only non-deterministic part of the pipeline. Once confirmed, all enforcement is fully deterministic.
```python
if report.passed:
    print("Contract ready. Review:")
    print(f"  deny:              {draft.deny}")
    print(f"  deny_commands:     {draft.deny_commands}")
    print(f"  only_domains:      {draft.only_domains}")
    print(f"  value_range:       {draft.value_range}")
    print(f"  obligation_timing: {draft.obligation_timing}")

    confirm = input("Activate this contract? [y/N]: ")
    if confirm.lower() == "y":
        active_contract = draft
        print("Contract activated.")
else:
    print("Issues found — review before activating:")
    for issue in report.issues:
        print(f"  WARNING: {issue}")
```

### The complete trust boundary
```
AGENTS.md (human-written, version-controlled)
    │
    ▼  translate_to_contract()    ← only non-deterministic step
Draft IntentContract
    │
    ▼  validate_contract_draft()  ← deterministic quality check
Validation Report (issues / passed)
    │
    ▼  Human confirms             ← explicit human gate
Active IntentContract
    │
    ▼  check() / enforce()        ← fully deterministic, 0.042ms
ALLOW / DENY + CIEU record (SHA-256 chained, tamper-evident)
```

Once a contract is active, **no LLM is involved in any enforcement decision**. Every ALLOW and DENY is computed deterministically from the rules you confirmed. Every decision is written to the CIEU audit chain with the SHA-256 hash of the contract that produced it — auditors can verify exactly which version of your policy governed each agent action.


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

## Advanced Features

### ObligationTrigger — Automatic Follow-Up Obligations

When certain tool calls are allowed, Y*gov can automatically create follow-up obligations that agents must fulfill. This bridges tool-call-layer governance with obligation-layer governance.

**Example use case:** After a web search tool call, automatically create an obligation to update the knowledge base within 30 minutes.

```python
from ystar.governance.obligation_triggers import ObligationTrigger, TriggerRegistry

trigger = ObligationTrigger(
    trigger_id="research_knowledge_update",
    trigger_tool_pattern=r"web_search|WebSearch",
    obligation_type="knowledge_update_required",
    description="After web research, update knowledge base with findings",
    target_agent="caller",
    deadline_seconds=1800,
    severity="SOFT"
)
```

Available in v0.41.1. Full documentation coming in v0.42.

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

📡 **Live operations:** https://t.me/YstarBridgeLabs
🏢 **Company repo:** https://github.com/liuhaotian2024-prog/ystar-bridge-labs

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

## Badge

If your project uses Y*gov, add this badge to your README:

```markdown
[![Y*gov governed](https://img.shields.io/badge/governed%20by-Y*gov-brightgreen)](https://github.com/liuhaotian2024-prog/Y-star-gov)
```

---

## Repository

**Source:** https://github.com/liuhaotian2024-prog/Y-star-gov
**Issues:** https://github.com/liuhaotian2024-prog/Y-star-gov/issues
**Docs:** https://ystar-gov.com (coming soon)



