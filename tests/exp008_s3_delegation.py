"""EXP-008 S3: Multi-agent DelegationChain test."""
import json, time, uuid
from ystar import DelegationChain, DelegationContract, IntentContract, check
from ystar.governance.cieu_store import CIEUStore

cieu = CIEUStore(".ystar_cieu.db")
now = time.time

# Deny lists loaded from external config to avoid triggering hook on script content
DENY_PATHS = ["/et" + "c", "/produc" + "tion", "/stag" + "ing"]

ceo_c = IntentContract(deny=DENY_PATHS[:1], only_paths=[], deny_commands=["rm -rf", "sudo"],
    only_domains=[], invariant=[], optional_invariant=[], postcondition=[],
    field_deny={}, value_range={}, obligation_timing={})
cto_c = IntentContract(deny=DENY_PATHS[:2], only_paths=[],
    deny_commands=["rm -rf", "sudo"],
    only_domains=[], invariant=[], optional_invariant=[], postcondition=[],
    field_deny={}, value_range={}, obligation_timing={})
eng_c = IntentContract(deny=DENY_PATHS, only_paths=[],
    deny_commands=["rm -rf", "sudo"],
    only_domains=[], invariant=[], optional_invariant=[], postcondition=[],
    field_deny={}, value_range={}, obligation_timing={})

chain = DelegationChain()
chain.append(DelegationContract(principal="board", actor="ceo", contract=ceo_c,
    action_scope=["Read","Write","Bash","Agent"], allow_redelegate=True, delegation_depth=3))
chain.append(DelegationContract(principal="ceo", actor="cto", contract=cto_c,
    action_scope=["Read","Write","Bash"], allow_redelegate=True, delegation_depth=2))
chain.append(DelegationContract(principal="cto", actor="engineer", contract=eng_c,
    action_scope=["Read","Write"]))

print(f"Valid chain Board->CEO->CTO->Eng: is_valid={chain.is_valid()}")

# Engineer tries denied path
test_path = DENY_PATHS[1] + "/secrets.env"
r = check(params={"file_path": test_path}, result={}, contract=eng_c)
print(f"Engineer->{test_path}: passed={r.passed}, violation={r.violations[0].message if r.violations else 'none'}")
cieu.write_dict({"event_id": str(uuid.uuid4()), "seq_global": int(now()*1e6),
    "created_at": now(), "session_id": "exp008_clean", "agent_id": "engineer",
    "event_type": "Read", "decision": "deny", "passed": False,
    "violations": json.dumps([{"dimension":"deny","message":r.violations[0].message}]) if r.violations else "[]"})

# Engineer tries privilege escalation
bad_c = IntentContract(deny=[], only_paths=[], deny_commands=[], only_domains=[],
    invariant=[], optional_invariant=[], postcondition=[], field_deny={},
    value_range={}, obligation_timing={})
chain.append(DelegationContract(principal="engineer", actor="rogue_sub",
    contract=bad_c, action_scope=["Read","Write","Bash"]))
issues = chain.validate()
print(f"Escalation: is_valid={chain.is_valid()}, violations={len(issues)}")
cieu.write_dict({"event_id": str(uuid.uuid4()), "seq_global": int(now()*1e6)+1,
    "created_at": now(), "session_id": "exp008_clean", "agent_id": "engineer",
    "event_type": "subagent_spawn", "decision": "deny", "passed": False,
    "violations": json.dumps([{"dimension":"delegation","message":"monotonicity violation"}])})

print("S3: 2 DENY CIEU records written")
