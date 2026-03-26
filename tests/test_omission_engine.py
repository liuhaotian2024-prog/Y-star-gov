"""
tests/test_omission_engine.py — OmissionEngine 幂等性、双阶段超时
"""
import pytest
import time
import uuid

from ystar.governance.omission_engine import OmissionEngine, EngineResult
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, GovernanceEvent, GEventType, Severity
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_rules import reset_registry
from ystar.governance.cieu_store import NullCIEUStore, CIEUStore


def make_obligation(overdue_secs=0, hard_overdue_secs=30.0,
                    pre_status=None) -> ObligationRecord:
    """创建义务，overdue_secs > 0 表示已经超期多少秒"""
    now = time.time()
    due_at = now - overdue_secs if overdue_secs > 0 else now + 300
    ob = ObligationRecord(
        obligation_id=uuid.uuid4().hex[:8],
        entity_id="test_entity",
        actor_id="test_agent",
        obligation_type="respond_to_complaint",
        trigger_event_id=uuid.uuid4().hex[:8],
        required_event_types=["complaint_processed"],
        due_at=due_at,               # effective_due_at 由 due_at 计算
        hard_overdue_secs=hard_overdue_secs,
        severity=Severity.MEDIUM,
        created_at=now - 400,
        updated_at=now,
    )
    if pre_status:
        ob.status = pre_status
        if pre_status == ObligationStatus.SOFT_OVERDUE:
            ob.soft_violation_at = now - overdue_secs
    return ob


def make_engine(cieu_store=None) -> OmissionEngine:
    store = InMemoryOmissionStore()
    registry = reset_registry()
    engine = OmissionEngine(
        store=store,
        registry=registry,
        cieu_store=cieu_store or NullCIEUStore(),
    )
    return engine


# ── 幂等性 ───────────────────────────────────────────────────────────────────

class TestScanIdempotency:

    def test_scan_twice_no_duplicate_soft_violations(self):
        """连续两次 scan，soft violation 不重复"""
        engine = make_engine()
        ob = make_obligation(overdue_secs=10)
        engine.store.add_obligation(ob)

        engine.scan()
        engine.scan()

        violations = engine.store.list_violations()
        ids = [v.violation_id for v in violations]
        assert len(ids) == len(set(ids)), "Duplicate violations detected"

    def test_scan_ten_times_single_soft_violation(self):
        """扫描10次，只产生1条 soft violation（hard 还没到）"""
        engine = make_engine()
        ob = make_obligation(overdue_secs=5, hard_overdue_secs=999)
        engine.store.add_obligation(ob)

        for _ in range(10):
            engine.scan()

        violations = engine.store.list_violations()
        soft = [v for v in violations if v.details.get("stage") != "hard_overdue"]
        assert len(soft) == 1, f"Expected 1 soft violation, got {len(soft)}"

    def test_no_violation_when_pending_not_overdue(self):
        """未超期的义务不产生 violation"""
        engine = make_engine()
        ob = make_obligation(overdue_secs=0)  # due_at=now+300, 未超期
        engine.store.add_obligation(ob)
        r = engine.scan()
        assert r.is_clean()

    def test_clean_result_empty_store(self):
        engine = make_engine()
        r = engine.scan()
        assert r.is_clean()


# ── 双阶段超时 ───────────────────────────────────────────────────────────────

class TestTwoPhaseTimeout:

    def test_soft_overdue_status_after_first_scan(self):
        engine = make_engine()
        ob = make_obligation(overdue_secs=5)
        engine.store.add_obligation(ob)
        r = engine.scan()

        assert len(r.violations) >= 1
        updated = engine.store.get_obligation(ob.obligation_id)
        if updated:
            assert updated.status in (
                ObligationStatus.SOFT_OVERDUE,
                ObligationStatus.HARD_OVERDUE,
            )

    def test_hard_overdue_after_threshold(self):
        """SOFT_OVERDUE 状态 + 超过 hard_overdue_secs → HARD_OVERDUE"""
        engine = make_engine()
        # hard_overdue_secs=5，已超期 50 秒，远超阈值
        ob = make_obligation(overdue_secs=50, hard_overdue_secs=5,
                             pre_status=ObligationStatus.SOFT_OVERDUE)
        ob.soft_violation_at = time.time() - 50
        engine.store.add_obligation(ob)

        engine.scan()
        updated = engine.store.get_obligation(ob.obligation_id)
        if updated:
            assert updated.status == ObligationStatus.HARD_OVERDUE

    def test_violation_produced_on_overdue(self):
        engine = make_engine()
        ob = make_obligation(overdue_secs=10)
        engine.store.add_obligation(ob)
        r = engine.scan()
        assert len(r.violations) >= 1
        assert len(r.expired) >= 1


# ── CIEU 集成 ────────────────────────────────────────────────────────────────

class TestCIEUIntegration:

    def test_null_cieu_no_crash(self):
        engine = make_engine(cieu_store=NullCIEUStore())
        ob = make_obligation(overdue_secs=10)
        engine.store.add_obligation(ob)
        r = engine.scan()
        assert isinstance(r, EngineResult)

    def test_none_becomes_null_store(self):
        engine = OmissionEngine(
            store=InMemoryOmissionStore(),
            cieu_store=None,
        )
        assert engine.cieu_store is not None
        assert isinstance(engine.cieu_store, NullCIEUStore)

    def test_real_cieu_no_crash(self, tmp_db):
        cieu = CIEUStore(tmp_db)
        engine = make_engine(cieu_store=cieu)
        ob = make_obligation(overdue_secs=10)
        engine.store.add_obligation(ob)
        r = engine.scan()
        assert isinstance(r, EngineResult)


# ── 事件注入 ─────────────────────────────────────────────────────────────────

class TestEventIngestion:

    def test_ingest_event_no_crash(self):
        engine = make_engine()
        ev = GovernanceEvent(
            event_id=uuid.uuid4().hex,
            entity_id="e1",
            actor_id="agent_a",
            event_type=GEventType.ENTITY_CREATED,
            ts=time.time(),
        )
        result = engine.ingest_event(ev)
        assert isinstance(result, EngineResult)

    def test_summary_str(self):
        engine = make_engine()
        ob = make_obligation(overdue_secs=10)
        engine.store.add_obligation(ob)
        r = engine.scan()
        assert isinstance(r.summary(), str)
        assert len(r.summary()) > 0

    def test_clean_summary(self):
        engine = make_engine()
        r = engine.scan()
        assert r.summary() == "clean"
