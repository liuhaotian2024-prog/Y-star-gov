"""
Y*gov Quickstart API Guide
===========================

This file shows the 10 core symbols a new user needs to get started.
Y*gov exports 481 symbols, but most users only need these core APIs.

For complete documentation, see: https://github.com/liuhaotian2024-prog/Y-star-gov
"""

# ══════════════════════════════════════════════════════════════════════
# 1. Core Contract Types
# ══════════════════════════════════════════════════════════════════════

from ystar import IntentContract, Policy

# IntentContract: Define behavioral constraints for a function or agent
contract = IntentContract(
    deny=[".env", "/etc/"],              # Forbidden substrings
    only_paths=["./workspace/"],          # Path whitelist
    deny_commands=["rm -rf", "sudo"],     # Command blocklist
    only_domains=["api.internal.com"],    # Domain whitelist
    invariant=["amount > 0", "amount < 1000000"],  # Logic constraints
    value_range={"amount": {"min": 0, "max": 1000000}}  # Numeric bounds
)

# Policy: Alias for IntentContract (legacy compatibility)
policy = Policy(
    deny=["production"],
    only_paths=["./src/", "./tests/"]
)


# ══════════════════════════════════════════════════════════════════════
# 2. Permission Checking
# ══════════════════════════════════════════════════════════════════════

from ystar import check, CheckResult

# check(): Verify if a proposed action satisfies the contract
result = check(
    params={"file_path": "./workspace/data.txt", "amount": 500},
    output={},
    contract=contract
)

if result.passed:
    print("ALLOW")
    # Execute the action
else:
    print("DENY")
    for violation in result.violations:
        print(f"  - {violation.dimension}: {violation.message}")


# ══════════════════════════════════════════════════════════════════════
# 3. Full Governance Pipeline (Permission + CIEU + Obligations)
# ══════════════════════════════════════════════════════════════════════

from ystar import enforce

# enforce(): Complete governance pipeline
# Returns: (decision, cieu_records)
# decision: "allow" | "deny" | "escalate"
# cieu_records: List of tamper-evident audit records

decision, records = enforce(
    event_type="Write",
    agent_id="data_processor",
    params={"file_path": "./workspace/output.csv"},
    contract=contract,
    session_id="my_session"
)

if decision == "allow":
    print("Action permitted and logged to CIEU chain")
elif decision == "deny":
    print("Action blocked")
elif decision == "escalate":
    print("Human review required")


# ══════════════════════════════════════════════════════════════════════
# 4. Natural Language → Contract Translation
# ══════════════════════════════════════════════════════════════════════

from ystar.kernel.nl_to_contract import translate_to_contract

# Translate plain English rules to IntentContract
policy_text = """
# Agent Rules
- Never access /production or /staging
- Only call: api.stripe.com, api.internal.com
- Maximum transaction: $10,000
- Never run rm, sudo, or git push --force
"""

contract_dict, method, confidence = translate_to_contract(policy_text)
# method: "llm" (if ANTHROPIC_API_KEY set) or "regex" (fallback)
# confidence: 0.90 (LLM) or 0.50 (regex)

auto_contract = IntentContract(
    deny=contract_dict.get("deny", []),
    only_domains=contract_dict.get("only_domains", []),
    deny_commands=contract_dict.get("deny_commands", []),
    value_range=contract_dict.get("value_range", {})
)


# ══════════════════════════════════════════════════════════════════════
# 5. Obligation Tracking (Omission Governance)
# ══════════════════════════════════════════════════════════════════════

from ystar import OmissionEngine, ObligationRecord

# OmissionEngine: Track and enforce obligations
engine = OmissionEngine()

# Create obligation
obligation = ObligationRecord(
    obligation_id="task_001",
    agent_id="worker_agent",
    obligation_type="task_completion",
    description="Fix bug in payment processing module",
    deadline=time.time() + 3600,  # 1 hour from now
    severity="SOFT",  # or "HARD"
    context={"task_ticket_id": "TASK-123"}
)

engine.track(obligation)

# When agent makes next tool call, engine automatically checks obligations
violations = engine.scan(agent_id="worker_agent", current_time=time.time())
for v in violations:
    print(f"Obligation {v.obligation_id} is overdue")


# ══════════════════════════════════════════════════════════════════════
# 6. Delegation Chain (Multi-Agent Permission Inheritance)
# ══════════════════════════════════════════════════════════════════════

from ystar import DelegationChain, DelegationContract

# DelegationChain: Enforce monotonic authority across parent-child agents
parent_contract = IntentContract(
    deny=["/production"],
    only_paths=["./workspace/"]
)

child_contract = IntentContract(
    deny=["/production", "/staging"],  # Stricter than parent
    only_paths=["./workspace/temp/"]    # Subset of parent
)

chain = DelegationChain()
chain.add_delegation(
    parent_id="manager",
    child_id="worker",
    parent_contract=parent_contract,
    child_contract=child_contract
)

# Validate delegation
is_valid = chain.validate("manager", "worker")
if is_valid:
    print("Delegation valid: child permissions are subset of parent")
else:
    print("Delegation DENIED: child permissions exceed parent scope")


# ══════════════════════════════════════════════════════════════════════
# 7. OpenClaw Integration (Multi-Agent Framework)
# ══════════════════════════════════════════════════════════════════════

from ystar.domains.openclaw import (
    OpenClawDomainPack,
    make_openclaw_chain,
    make_session,
    enforce as openclaw_enforce,
    OpenClawEvent,
    EventType
)

# Create domain pack with 6 role-based contracts
pack = OpenClawDomainPack(
    workspace_root="./workspace",
    doc_domains=["docs.python.org", "github.com"]
)

# Build delegation chain: planner -> coder -> tester
chain = make_openclaw_chain(
    pack=pack,
    allowed_paths=["./src", "./tests"],
    allowed_domains=None,
    include_release=False
)

# Create session
session = make_session(
    session_id="demo",
    allowed_paths=["./src"],
    pack=pack,
    chain=chain,
    strict=False
)

# Enforce governance on tool call
event = OpenClawEvent(
    event_type=EventType.FILE_WRITE,
    agent_id="coder_agent",
    session_id="demo",
    file_path="./src/main.py",
    patch_summary="Fix null pointer bug",
    task_ticket_id="TASK-001"
)

decision, cieu_records = openclaw_enforce(event, session)
# decision: EnforceDecision.ALLOW / DENY / ESCALATE


# ══════════════════════════════════════════════════════════════════════
# 8. CLI Commands
# ══════════════════════════════════════════════════════════════════════

"""
Three-step integration with Claude Code:

1. Initialize session config:
   $ ystar setup

2. Install governance hook:
   $ ystar hook-install

3. Create AGENTS.md with your rules:
   # My Rules
   - Never modify /production
   - Only write to ./workspace/

Common commands:
  ystar doctor    - Health check (7 diagnostic tests)
  ystar report    - Governance report (decisions, deny rate)
  ystar verify    - Verify CIEU chain integrity
  ystar simulate  - A/B comparison (with vs without Y*gov)
  ystar audit     - Causal audit report
"""


# ══════════════════════════════════════════════════════════════════════
# 9. CIEU Audit Records
# ══════════════════════════════════════════════════════════════════════

"""
Every enforce() call writes a tamper-evident CIEU record:

{
  "seq_global": 1234,
  "event_id": "uuid",
  "agent_id": "worker_agent",
  "event_type": "Write",
  "decision": "allow",
  "violations": [],
  "contract_hash": "sha256:...",
  "file_path": "./workspace/data.txt",
  "prev_hash": "sha256:...",  # Links to previous record
  "record_hash": "sha256:...", # Hash of this record
  "created_at": 1234567890
}

Verify chain integrity:
  $ ystar verify --session my_session
"""


# ══════════════════════════════════════════════════════════════════════
# 10. Complete Example: Governed Agent
# ══════════════════════════════════════════════════════════════════════

import time
from ystar import IntentContract, enforce

def governed_agent_example():
    """Complete example: agent with Y*gov governance"""

    # 1. Define contract
    contract = IntentContract(
        deny=["/etc", "/root", "production"],
        only_paths=["./workspace/"],
        deny_commands=["rm -rf", "sudo", "git push --force"],
        invariant=["amount > 0", "amount < 100000"]
    )

    # 2. Agent attempts an action
    proposed_action = {
        "file_path": "./workspace/results.json",
        "amount": 5000
    }

    # 3. Check before execution
    decision, records = enforce(
        event_type="Write",
        agent_id="analyst_agent",
        params=proposed_action,
        contract=contract,
        session_id="analysis_session"
    )

    # 4. Execute only if allowed
    if decision == "allow":
        print(f"✓ Action allowed and logged (seq={records[0].seq_global})")
        # Execute: write_file(proposed_action["file_path"], data)
    else:
        print(f"✗ Action denied")
        for r in records:
            if r.violations:
                print(f"  Violations: {r.violations}")

    return decision, records


# ══════════════════════════════════════════════════════════════════════
# Summary: The 10 Core Symbols
# ══════════════════════════════════════════════════════════════════════

"""
1. IntentContract       - Define behavioral constraints
2. check()              - Permission checking (0.042ms mean latency)
3. enforce()            - Full pipeline (permission + CIEU + obligations)
4. translate_to_contract() - Natural language → contract
5. OmissionEngine       - Obligation tracking
6. DelegationChain      - Multi-agent permission inheritance
7. OpenClawDomainPack   - Pre-built role contracts for OpenClaw
8. CLI: ystar setup/doctor/verify/report
9. CIEU records         - Tamper-evident audit chain
10. Complete example    - Governed agent pattern

For complete API reference:
  from ystar import *
  help(IntentContract)
  help(check)
  help(enforce)
"""

if __name__ == "__main__":
    # Run the complete example
    governed_agent_example()
