"""
tests/test_omission_engine.py — OmissionEngine 幂等性、双阶段超时、live-reload
"""
import pytest
import time
import uuid

from ystar.governance.omission_engine import OmissionEngine, EngineResult
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, GovernanceEvent, GEventType, Severity,
    RestorationResult, OmissionType,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_rules import reset_registry
from ystar.governance.cieu_store import NullCIEUStore, CIEUStore
from ystar.governance.obligation_triggers import (
    ObligationTrigger, TriggerRegistry, reset_trigger_registry
)


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


# ── Restoration 机制 ─────────────────────────────────────────────────────────

class TestRestoration:
    """Test restoration mechanism for expired/violated obligations."""

    def test_restore_expired_obligation_success(self):
        """成功恢复过期的 obligation"""
        engine = make_engine()
        now = time.time()

        # 创建已过期的 obligation（overdue 10秒）
        ob = make_obligation(overdue_secs=10, hard_overdue_secs=30)
        engine.store.add_obligation(ob)

        # scan 使其变为 SOFT_OVERDUE
        r = engine.scan()
        assert len(r.expired) == 1

        # 恢复（默认 grace period = 2x original deadline）
        result = engine.restore_obligation(ob.obligation_id, ob.actor_id)

        assert result.success is True
        assert result.obligation_id == ob.obligation_id
        assert result.actor_id == ob.actor_id
        assert result.restored_at is not None
        assert result.failure_reason is None
        assert result.governance_event_id is not None

        # 验证 obligation 状态已变为 RESTORED
        restored_ob = engine.store.get_obligation(ob.obligation_id)
        assert restored_ob.status == ObligationStatus.RESTORED
        assert restored_ob.restored_at is not None
        assert restored_ob.restored_by_event_id == result.governance_event_id

        # 验证 OBLIGATION_RESTORED 事件已写入
        events = engine.store.events_for_entity(ob.entity_id)
        restored_events = [e for e in events if e.event_type == GEventType.OBLIGATION_RESTORED]
        assert len(restored_events) == 1
        assert restored_events[0].event_id == result.governance_event_id

    def test_restore_hard_overdue_success(self):
        """恢复 HARD_OVERDUE 状态的 obligation"""
        engine = make_engine()
        now = time.time()

        # 创建 HARD_OVERDUE obligation
        ob = make_obligation(overdue_secs=100, hard_overdue_secs=30)
        ob.status = ObligationStatus.HARD_OVERDUE
        ob.hard_violation_at = now - 70
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(ob.obligation_id, ob.actor_id)

        assert result.success is True
        restored_ob = engine.store.get_obligation(ob.obligation_id)
        assert restored_ob.status == ObligationStatus.RESTORED

    def test_restore_beyond_grace_period_fails(self):
        """超出恢复宽限期后恢复失败"""
        engine = make_engine()
        now = time.time()

        # 创建一个原始deadline=400秒的过期 obligation
        # grace_period = 400 * 2.0 = 800秒
        # 让它超期 1000 秒（超出恢复宽限期）
        ob = ObligationRecord(
            obligation_id="ob_too_late",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="late_response",
            required_event_types=["response"],
            due_at=now - 1000,  # 1000秒前就该完成
            created_at=now - 1400,  # 原始deadline = 1400-1000 = 400秒
            status=ObligationStatus.EXPIRED,
            restoration_grace_period_multiplier=2.0,
        )
        engine.store.add_obligation(ob)

        # 尝试恢复（应失败）
        result = engine.restore_obligation(ob.obligation_id, ob.actor_id)

        assert result.success is False
        assert result.failure_reason == "beyond_grace_period"

        # 验证状态未改变
        ob_after = engine.store.get_obligation(ob.obligation_id)
        assert ob_after.status == ObligationStatus.EXPIRED

    def test_restore_not_found(self):
        """obligation 不存在时返回失败"""
        engine = make_engine()
        result = engine.restore_obligation("nonexistent_id", "some_actor")

        assert result.success is False
        assert result.failure_reason == "not_found"

    def test_restore_wrong_actor(self):
        """actor_id 不匹配时返回失败"""
        engine = make_engine()
        ob = make_obligation(overdue_secs=10)
        ob.status = ObligationStatus.SOFT_OVERDUE
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(ob.obligation_id, "wrong_actor")

        assert result.success is False
        assert result.failure_reason == "wrong_actor"

    def test_restore_not_restorable_status(self):
        """不可恢复状态（如 FULFILLED）返回失败"""
        engine = make_engine()
        ob = make_obligation(overdue_secs=0)
        ob.status = ObligationStatus.FULFILLED
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(ob.obligation_id, ob.actor_id)

        assert result.success is False
        assert result.failure_reason == "not_restorable"

    def test_restoration_bypasses_gate(self):
        """restoration 动作不被 intervention gate 阻断"""
        from ystar.governance.intervention_engine import InterventionEngine, GatingPolicy

        engine = make_engine()
        intervention_engine = InterventionEngine(
            omission_store=engine.store,
            gating_policy=GatingPolicy(),
        )

        # 创建过期义务，让 scan() 自然推进状态：PENDING → SOFT → HARD
        # overdue_secs=100 表示已过期100秒，hard_overdue_secs=30 表示30秒后进入 HARD
        # scan() 在单次扫描中会同时完成 PENDING → SOFT_OVERDUE → HARD_OVERDUE 转换
        ob = make_obligation(overdue_secs=100, hard_overdue_secs=30)
        engine.store.add_obligation(ob)

        # scan：PENDING → SOFT_OVERDUE → HARD_OVERDUE（创建 soft + hard violation）
        r = engine.scan()

        # 验证状态已转为 HARD_OVERDUE
        ob_after = engine.store.get_obligation(ob.obligation_id)
        assert ob_after.status == ObligationStatus.HARD_OVERDUE, \
            f"Expected HARD_OVERDUE, got {ob_after.status}"

        # 找到 hard violation（process_violations 需要 hard violation 才会创建 INTERRUPT_GATE pulse）
        hard_violations = [v for v in r.violations if v.details.get("stage") == "hard_overdue"]
        assert len(hard_violations) >= 1, \
            f"Expected at least 1 hard violation, got {len(hard_violations)}"

        # process_violations 会创建 INTERRUPT_GATE pulse
        intervention_result = intervention_engine.process_violations(hard_violations)
        assert len(intervention_result.pulses_fired) >= 1, \
            f"Expected at least 1 pulse fired, got {len(intervention_result.pulses_fired)}"

        # 验证 gate 会阻断高风险动作
        gate_result_deny = intervention_engine.gate_check(
            ob.actor_id,
            "entity_created",  # 高风险动作
        )
        assert gate_result_deny.decision.value == "deny"

        # 验证 OBLIGATION_RESTORED 动作永远放行
        gate_result_restore = intervention_engine.gate_check(
            ob.actor_id,
            GEventType.OBLIGATION_RESTORED,
        )
        assert gate_result_restore.decision.value == "allow"

    def test_can_restore_method(self):
        """测试 ObligationRecord.can_restore() 方法"""
        now = time.time()

        # 可恢复：EXPIRED + 在 grace period 内
        ob1 = ObligationRecord(
            obligation_id="ob1",
            entity_id="e1",
            actor_id="a1",
            obligation_type="t1",
            due_at=now - 100,
            created_at=now - 500,  # deadline = 400秒
            status=ObligationStatus.EXPIRED,
            restoration_grace_period_multiplier=2.0,  # grace = 800秒
        )
        assert ob1.can_restore(now) is True

        # 不可恢复：超出 grace period
        ob2 = ObligationRecord(
            obligation_id="ob2",
            entity_id="e2",
            actor_id="a2",
            obligation_type="t2",
            due_at=now - 1000,
            created_at=now - 1400,  # deadline = 400秒, grace = 800秒
            status=ObligationStatus.EXPIRED,
            restoration_grace_period_multiplier=2.0,
        )
        assert ob2.can_restore(now) is False

        # 不可恢复：状态是 FULFILLED
        ob3 = ObligationRecord(
            obligation_id="ob3",
            entity_id="e3",
            actor_id="a3",
            obligation_type="t3",
            due_at=now - 100,
            created_at=now - 500,
            status=ObligationStatus.FULFILLED,
            restoration_grace_period_multiplier=2.0,
        )
        assert ob3.can_restore(now) is False

    def test_restoration_deadline_calculation(self):
        """测试 restoration_deadline 计算逻辑"""
        now = time.time()

        ob = ObligationRecord(
            obligation_id="ob",
            entity_id="e",
            actor_id="a",
            obligation_type="t",
            due_at=now + 1000,
            created_at=now,
            restoration_grace_period_multiplier=3.0,
        )

        # restoration_deadline = due_at + (due_at - created_at) * 3.0
        #                      = (now+1000) + 1000 * 3.0
        #                      = now + 4000
        expected = now + 4000
        actual = ob.restoration_deadline()
        assert abs(actual - expected) < 1.0  # 允许浮点误差


# ── Live-Reload Trigger Registration ────────────────────────────────────────

class TestLiveReload:
    """Test live-reload: new trigger registration immediately scans pending events."""

    def test_trigger_registration_with_engine_creates_retroactive_obligations(self):
        """When a new trigger is registered with engine parameter, immediately scan events."""
        # Setup: create engine with trigger registry
        store = InMemoryOmissionStore()
        trigger_registry = reset_trigger_registry()
        engine = OmissionEngine(
            store=store,
            registry=reset_registry(),
            cieu_store=NullCIEUStore(),
            trigger_registry=trigger_registry,
        )

        # Register entity first
        from ystar.governance.omission_models import TrackedEntity, EntityStatus
        entity = TrackedEntity(
            entity_id="session_001",
            entity_type="session",
            initiator_id="test_agent",
            current_owner_id="test_agent",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Inject a tool_call event BEFORE registering the trigger
        ev = GovernanceEvent(
            event_id=uuid.uuid4().hex[:8],
            event_type="tool_call",
            entity_id="session_001",
            actor_id="test_agent",
            ts=time.time(),
            payload={
                "tool_name": "WebSearch",
                "tool_input": {"query": "governance patterns"},
                "decision": "ALLOW",
            }
        )
        engine.ingest_event(ev)

        # Verify: no obligations yet (trigger not registered)
        assert len(store.list_obligations()) == 0

        # NOW: register new trigger with live-reload (pass engine parameter)
        new_trigger = ObligationTrigger(
            trigger_id="test_live_reload",
            trigger_tool_pattern=r"WebSearch",
            obligation_type=OmissionType.KNOWLEDGE_UPDATE_REQUIRED,
            description="Test live-reload: knowledge update after WebSearch",
            target_agent="caller",
            deadline_seconds=1800,
            severity="SOFT",
            fulfillment_event="file_write",
            required_event_types=["file_write"],
            enabled=True,
            deduplicate=True,
        )
        trigger_registry.register(new_trigger, engine=engine)

        # Verify: obligation was created retroactively from the earlier event
        obligations = store.list_obligations()
        assert len(obligations) == 1
        ob = obligations[0]
        assert ob.obligation_type == OmissionType.KNOWLEDGE_UPDATE_REQUIRED
        assert ob.actor_id == "test_agent"
        assert ob.entity_id == "session_001"
        assert ob.triggered_by_event_id == ev.event_id

    def test_live_reload_skips_deny_events(self):
        """Live-reload only creates obligations for ALLOW decisions, not DENY."""
        store = InMemoryOmissionStore()
        trigger_registry = reset_trigger_registry()
        engine = OmissionEngine(
            store=store,
            registry=reset_registry(),
            cieu_store=NullCIEUStore(),
            trigger_registry=trigger_registry,
        )

        # Inject DENY event
        ev_deny = GovernanceEvent(
            event_id=uuid.uuid4().hex[:8],
            event_type="tool_call",
            entity_id="session_002",
            actor_id="test_agent",
            ts=time.time(),
            payload={
                "tool_name": "Write",
                "tool_input": {"file_path": "AGENTS.md"},
                "decision": "DENY",
            }
        )
        engine.ingest_event(ev_deny)

        # Register trigger
        trigger_registry.register(
            ObligationTrigger(
                trigger_id="write_trigger",
                trigger_tool_pattern=r"Write",
                obligation_type=OmissionType.TECHNICAL_REVIEW_REQUIRED,
                description="Test DENY skip",
                target_agent="caller",
                deadline_seconds=3600,
                severity="SOFT",
                fulfillment_event="review_complete",
                required_event_types=["review_complete"],
            ),
            engine=engine
        )

        # Verify: no obligation created (DENY events don't trigger obligations in live-reload)
        assert len(store.list_obligations()) == 0

    def test_live_reload_deduplicates(self):
        """Live-reload respects deduplicate flag and doesn't create duplicate obligations."""
        store = InMemoryOmissionStore()
        trigger_registry = reset_trigger_registry()
        engine = OmissionEngine(
            store=store,
            registry=reset_registry(),
            cieu_store=NullCIEUStore(),
            trigger_registry=trigger_registry,
        )

        # Register entity first
        from ystar.governance.omission_models import TrackedEntity, EntityStatus
        entity = TrackedEntity(
            entity_id="session_003",
            entity_type="session",
            initiator_id="test_agent",
            current_owner_id="test_agent",
            status=EntityStatus.ACTIVE,
        )
        store.upsert_entity(entity)

        # Inject event
        ev = GovernanceEvent(
            event_id=uuid.uuid4().hex[:8],
            event_type="tool_call",
            entity_id="session_003",
            actor_id="test_agent",
            ts=time.time(),
            payload={
                "tool_name": "Edit",
                "tool_input": {"file_path": "content/blog.md"},
                "decision": "ALLOW",
            }
        )
        engine.ingest_event(ev)

        # Register trigger (with deduplicate=True)
        trigger = ObligationTrigger(
            trigger_id="edit_trigger",
            trigger_tool_pattern=r"Edit",
            obligation_type=OmissionType.TECHNICAL_REVIEW_REQUIRED,
            description="Test deduplication",
            target_agent="caller",
            deadline_seconds=7200,
            severity="SOFT",
            fulfillment_event="review_complete",
            required_event_types=["review_complete"],
            deduplicate=True,
        )
        trigger_registry.register(trigger, engine=engine)

        # Verify: obligation created
        assert len(store.list_obligations()) == 1

        # Try to register same trigger again (simulate re-registration)
        trigger_registry.register(trigger, engine=engine)

        # Verify: still only 1 obligation (deduplication worked)
        assert len(store.list_obligations()) == 1
