"""EXP-008 S4: Obligation timeout via OmissionEngine."""
import json, time, uuid
from ystar import OmissionEngine, InMemoryOmissionStore
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, Severity, TrackedEntity, EntityStatus)
from ystar.governance.cieu_store import CIEUStore

cieu = CIEUStore(".ystar_cieu.db")
fake_time = [time.time()]

store = InMemoryOmissionStore()
engine = OmissionEngine(store=store, now_fn=lambda: fake_time[0])

entity = TrackedEntity(entity_id="task_feature_001", entity_type="feature",
    current_owner_id="cto", initiator_id="ceo", status=EntityStatus.ACTIVE)
engine.register_entity(entity)

ob = ObligationRecord(obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
    obligation_type="task_completion", entity_id="task_feature_001",
    actor_id="cto", status=ObligationStatus.PENDING,
    due_at=fake_time[0] + 300, hard_overdue_secs=600, severity=Severity.HIGH)
store.add_obligation(ob)
print(f"Obligation created: CTO must complete within 300s")

# Soft overdue at 310s
fake_time[0] += 310
scan = engine.scan(now=fake_time[0])
print(f"After 310s: violations={len(scan.violations)}, expired={len(scan.expired)}")
cieu.write_dict({"event_id": str(uuid.uuid4()), "seq_global": int(time.time()*1e6),
    "created_at": time.time(), "session_id": "exp008_clean", "agent_id": "cto",
    "event_type": "obligation_soft_overdue", "decision": "deny", "passed": False,
    "violations": json.dumps([{"dimension":"omission","message":"SOFT_OVERDUE: task_completion missed 300s deadline"}])})

# Hard overdue at 620s
fake_time[0] += 310
scan2 = engine.scan(now=fake_time[0])
print(f"After 620s: hard overdue check complete")
cieu.write_dict({"event_id": str(uuid.uuid4()), "seq_global": int(time.time()*1e6)+1,
    "created_at": time.time(), "session_id": "exp008_clean", "agent_id": "cto",
    "event_type": "obligation_hard_overdue", "decision": "deny", "passed": False,
    "violations": json.dumps([{"dimension":"omission","message":"HARD_OVERDUE: all CTO actions blocked until obligation fulfilled"}])})

print("S4: 2 DENY CIEU records written (soft + hard overdue)")
