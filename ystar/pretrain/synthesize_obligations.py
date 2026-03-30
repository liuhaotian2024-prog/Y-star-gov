"""
预训练辅助：合成 obligation 数据
把 MAST 失败模式 + Who&When 正常任务 转成 ObligationRecord
让 GovernanceLoop 在预训练阶段有有意义的 health 评估
"""
import sys, time, uuid, warnings
warnings.filterwarnings("ignore")

from ystar.governance.omission_engine import (
    InMemoryOmissionStore, ObligationRecord, OmissionViolation,
    ObligationStatus
)
from ystar.governance.intervention_engine import InterventionEngine
from ystar.governance.reporting import ReportEngine
from ystar.governance.governance_loop import GovernanceLoop
from ystar.governance.metalearning import ConstraintRegistry
from ystar.governance.cieu_store import CIEUStore

now = time.time()

def make_obligation(
    trigger: str, obl_type: str, due_secs: float,
    fulfilled: bool, source: str, entity_id: str = "pretrain_agent"
) -> ObligationRecord:
    oid = f"ob_{uuid.uuid4().hex[:8]}"
    status = ObligationStatus.FULFILLED if fulfilled else ObligationStatus.HARD_OVERDUE
    return ObligationRecord(
        obligation_id       = oid,
        entity_id           = entity_id,
        actor_id            = entity_id,
        obligation_type     = obl_type,
        trigger_event_id    = f"evt_{trigger}_{uuid.uuid4().hex[:6]}",
        required_event_types= [obl_type],
        due_at              = now - 1.0,     # 已过期
        status              = status,
        fulfilled_by_event_id = f"evt_{uuid.uuid4().hex[:8]}" if fulfilled else None,
        severity            = 0.80 if not fulfilled else 0.0,
        notes               = source,
        created_at          = now - due_secs - 10,
        updated_at          = now - 1.0,
    )

def make_violation(
    ob: ObligationRecord, source: str
) -> OmissionViolation:
    return OmissionViolation(
        violation_id  = f"viol_{uuid.uuid4().hex[:8]}",
        entity_id     = ob.entity_id,
        obligation_id = ob.obligation_id,
        actor_id      = ob.actor_id,
        omission_type = "HARD_OVERDUE",
        detected_at   = now,
        overdue_secs  = 60.0,
        severity      = ob.severity,
        details       = source,
    )

# ── 合成记录集 ────────────────────────────────────────────────────────────────
MAST_OMISSIONS = [
    ("task_assigned", "acknowledgement", 300.0, False, "MAST:FM02 Context Loss"),
    ("task_assigned", "acknowledgement", 600.0, False, "MAST:FM05 Planning Failure"),
    ("task_done",     "completion",      300.0, False, "MAST:FM06 Verification Skip"),
    ("task_update",   "completion",      300.0, False, "MAST:FM10 Information Withholding"),
    ("task_done",     "completion",      600.0, False, "MAST:FM11 Premature Termination"),
]
NORMAL_COMPLETIONS = [
    ("task_done",   "completion",      300.0, True,  "WhoWhen:normal_task_1"),
    ("task_done",   "completion",      300.0, True,  "WhoWhen:normal_task_2"),
    ("task_update", "acknowledgement", 120.0, True,  "WhoWhen:normal_ack_1"),
    ("task_done",   "completion",      600.0, True,  "WhoWhen:normal_task_3"),
    ("task_assigned","acknowledgement",300.0, True,  "WhoWhen:normal_ack_2"),
    ("task_done",   "completion",      300.0, True,  "WhoWhen:normal_task_4"),
    ("task_done",   "completion",      300.0, True,  "WhoWhen:normal_task_5"),
]

ALL_OBLIGATIONS = MAST_OMISSIONS + NORMAL_COMPLETIONS
fulfilled_count = sum(1 for r in ALL_OBLIGATIONS if r[3])
print(f"合成 obligation: {len(ALL_OBLIGATIONS)} 条  "
      f"履行={fulfilled_count}  未履行={len(ALL_OBLIGATIONS)-fulfilled_count}")
print(f"履行率: {fulfilled_count/len(ALL_OBLIGATIONS):.1%}")


def build_pretrain_governance(cieu_store=None):
    """
    构建含合成 obligation 数据的 GovernanceLoop。
    用于预训练阶段让 health 评估有意义。
    返回 (omission_store, report_engine, gloop)
    """
    store = InMemoryOmissionStore()
    ie    = InterventionEngine(store)

    for trigger, obl_type, due_secs, fulfilled, source in ALL_OBLIGATIONS:
        ob = make_obligation(trigger, obl_type, due_secs, fulfilled, source)
        store.add_obligation(ob)
        if not fulfilled:
            viol = make_violation(ob, source)
            store.add_violation(viol)

    re_engine = ReportEngine(
        omission_store = store,
        cieu_store     = cieu_store,
        intervention_eng = ie,
    )
    gloop = GovernanceLoop(
        report_engine       = re_engine,
        constraint_registry = ConstraintRegistry(),
        intervention_engine = ie,
    )
    return store, re_engine, gloop


if __name__ == "__main__":
    # 测试
    import os
    from pathlib import Path
    OUT = Path(__file__).parent / "outputs"
    OUT.mkdir(exist_ok=True)
    cieu_db = str(OUT / "pretrain_cieu.db")
    cieu = CIEUStore(db_path=cieu_db) if os.path.exists(cieu_db) else None

    store, re_engine, gloop = build_pretrain_governance(cieu_store=cieu)
    report = re_engine.daily_report(label="synth_test")
    print(f"\nReportEngine with synth obligations:")
    print(f"  omissions.total_violations = {report.omissions.total_violations}")
    print(f"  obligations.fulfillment_rate = {report.obligations.fulfillment_rate:.1%}")
    print(f"  kpis = {list(report.kpis.keys())[:4]}")

    # 喂历史数据
    pretrain_jsonl = str(OUT / "pretrain_all_records.jsonl")
    n = gloop.bootstrap_from_jsonl(pretrain_jsonl)
    print(f"\nbootstrap: {n} 条")
    obs = gloop.observe_from_report_engine()
    print(f"观测: fulfillment={obs.obligation_fulfillment_rate:.1%}  "
          f"false_pos={obs.false_positive_rate:.1%}  "
          f"omission_detect={obs.omission_detection_rate:.1%}")
    r = gloop.tighten()
    print(f"\ntighten: health={r.overall_health}")
    print(f"  action: {(r.recommended_action or '')[:60]}")
    if r.contract_quality:
        q = r.contract_quality
        print(f"  quality: score={q.quality_score:.3f}  cov={q.coverage_rate:.0%}  fp={q.false_positive_rate:.0%}")
