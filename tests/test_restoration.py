"""
tests/test_restoration.py — Restoration Mechanism Tests

测试过期义务的补救恢复机制（v0.43 feature）。
"""
import pytest
import time
import uuid

from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import (
    ObligationRecord, ObligationStatus, GovernanceEvent, GEventType,
    Severity, RestorationResult,
)
from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_rules import reset_registry
from ystar.governance.cieu_store import NullCIEUStore


def make_test_engine():
    """创建测试用 OmissionEngine"""
    store = InMemoryOmissionStore()
    registry = reset_registry()
    engine = OmissionEngine(
        store=store,
        registry=registry,
        cieu_store=NullCIEUStore(),
    )
    return engine


def make_expired_obligation(
    engine: OmissionEngine,
    overdue_secs: float = 10.0,
    restoration_multiplier: float = 2.0,
) -> ObligationRecord:
    """
    创建一个已过期的义务。

    参数:
        overdue_secs: 过期多少秒
        restoration_multiplier: 恢复宽限期倍数

    返回已经标记为 EXPIRED 的 ObligationRecord。
    """
    now = time.time()

    # 计算 deadline duration（原始期限）
    deadline_duration = 100.0  # 100秒期限

    ob = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        entity_id="test_entity_restore",
        actor_id="test_agent",
        obligation_type="test_required_action",
        trigger_event_id=f"ev_{uuid.uuid4().hex[:8]}",
        required_event_types=["action_completed"],
        due_at=now - overdue_secs,  # 已经过期
        grace_period_secs=0.0,
        hard_overdue_secs=10.0,
        severity=Severity.MEDIUM,
        status=ObligationStatus.PENDING,
        restoration_grace_period_multiplier=restoration_multiplier,
        created_at=now - overdue_secs - deadline_duration,  # 保证 deadline_duration 正确
        updated_at=now,
    )

    engine.store.add_obligation(ob)

    # 触发扫描让它过期
    result = engine.scan(now=now)

    # 重新获取更新后的 obligation
    ob_updated = engine.store.get_obligation(ob.obligation_id)
    assert ob_updated is not None
    assert ob_updated.status in (
        ObligationStatus.SOFT_OVERDUE,
        ObligationStatus.HARD_OVERDUE,
        ObligationStatus.EXPIRED,
    ), f"Expected expired state, got {ob_updated.status}"

    return ob_updated


# ── 测试用例 ────────────────────────────────────────────────────────────────


class TestRestoreExpiredSuccess:
    """测试成功恢复过期义务"""

    def test_restore_soft_overdue_success(self):
        """SOFT_OVERDUE 状态可以成功恢复"""
        engine = make_test_engine()
        ob = make_expired_obligation(engine, overdue_secs=5.0)

        # 在 grace period 内恢复
        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert result.success, f"Restoration failed: {result.failure_reason}"
        assert result.obligation_id == ob.obligation_id
        assert result.restored_at is not None
        assert result.governance_event_id is not None

        # 验证状态更新
        ob_restored = engine.store.get_obligation(ob.obligation_id)
        assert ob_restored.status == ObligationStatus.RESTORED
        assert ob_restored.restored_at is not None
        assert ob_restored.restored_by_event_id == result.governance_event_id

    def test_restore_hard_overdue_success(self):
        """HARD_OVERDUE 状态可以成功恢复"""
        engine = make_test_engine()

        # 创建过期义务，并让它进入 HARD_OVERDUE
        now = time.time()
        deadline_duration = 100.0
        overdue_secs = 50.0  # 超过 hard_overdue_secs=10

        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_hard",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now - overdue_secs,
            hard_overdue_secs=10.0,
            restoration_grace_period_multiplier=3.0,  # 更长的恢复期
            created_at=now - overdue_secs - deadline_duration,
            updated_at=now,
        )
        engine.store.add_obligation(ob)
        engine.scan(now=now)

        ob_hard = engine.store.get_obligation(ob.obligation_id)
        assert ob_hard.status == ObligationStatus.HARD_OVERDUE

        # 恢复
        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert result.success
        ob_restored = engine.store.get_obligation(ob.obligation_id)
        assert ob_restored.status == ObligationStatus.RESTORED

    def test_restore_writes_governance_event(self):
        """恢复操作写入 OBLIGATION_RESTORED 事件"""
        engine = make_test_engine()
        ob = make_expired_obligation(engine, overdue_secs=5.0)

        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert result.success

        # 检查事件是否写入
        events = engine.store.events_for_entity(
            entity_id=ob.entity_id,
            event_types=[GEventType.OBLIGATION_RESTORED]
        )

        assert len(events) >= 1, "No OBLIGATION_RESTORED event found"
        ev = events[-1]
        assert ev.event_id == result.governance_event_id
        assert ev.entity_id == ob.entity_id
        assert ev.actor_id == ob.actor_id
        assert ev.payload.get("obligation_id") == ob.obligation_id


class TestRestoreBeyondGraceFails:
    """测试超出宽限期后恢复失败"""

    def test_restore_beyond_grace_period_fails(self):
        """超出 restoration grace period 后不能恢复"""
        engine = make_test_engine()
        now = time.time()

        deadline_duration = 100.0
        restoration_multiplier = 2.0

        # 创建过期很久的义务（超过 restoration deadline）
        # restoration_deadline = due_at + (deadline_duration * multiplier)
        #                     = (now - overdue_secs) + (100 * 2)
        # 要超出 restoration deadline，需要 overdue_secs > 200
        overdue_secs = 250.0

        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_late",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now - overdue_secs,
            restoration_grace_period_multiplier=restoration_multiplier,
            created_at=now - overdue_secs - deadline_duration,
            updated_at=now,
        )
        engine.store.add_obligation(ob)
        engine.scan(now=now)

        ob_expired = engine.store.get_obligation(ob.obligation_id)
        assert ob_expired.status in (ObligationStatus.SOFT_OVERDUE, ObligationStatus.EXPIRED)

        # 尝试恢复（应该失败）
        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert not result.success
        assert result.failure_reason == "beyond_grace_period"

        # 验证状态未改变
        ob_unchanged = engine.store.get_obligation(ob.obligation_id)
        assert ob_unchanged.status != ObligationStatus.RESTORED

    def test_restore_can_restore_helper_method(self):
        """验证 can_restore() 辅助方法的正确性"""
        engine = make_test_engine()
        now = time.time()

        deadline_duration = 100.0
        restoration_multiplier = 2.0

        # 在 grace period 内
        ob_within = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="test_action",
            required_event_types=["action_completed"],
            due_at=now - 50.0,  # 过期50秒
            status=ObligationStatus.EXPIRED,
            restoration_grace_period_multiplier=restoration_multiplier,
            created_at=now - 150.0,  # deadline_duration = 100s
            updated_at=now,
        )

        # restoration_deadline = (now - 50) + 100*2 = now + 150
        assert ob_within.can_restore(now), "Should be restorable within grace period"

        # 超出 grace period
        ob_beyond = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="test_action",
            required_event_types=["action_completed"],
            due_at=now - 250.0,  # 过期250秒
            status=ObligationStatus.EXPIRED,
            restoration_grace_period_multiplier=restoration_multiplier,
            created_at=now - 350.0,  # deadline_duration = 100s
            updated_at=now,
        )

        # restoration_deadline = (now - 250) + 100*2 = now - 50 (已过期)
        assert not ob_beyond.can_restore(now), "Should not be restorable beyond grace period"


class TestRestoreAlreadyFulfilledFails:
    """测试已完成义务不能恢复"""

    def test_restore_fulfilled_obligation_fails(self):
        """FULFILLED 状态的义务不能恢复"""
        engine = make_test_engine()
        now = time.time()

        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_fulfilled",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now + 100,  # 还未到期
            status=ObligationStatus.FULFILLED,  # 已完成
            fulfilled_by_event_id=f"ev_{uuid.uuid4().hex[:8]}",
            created_at=now - 50,
            updated_at=now,
        )
        engine.store.add_obligation(ob)

        # 尝试恢复（应该失败）
        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert not result.success
        assert result.failure_reason == "not_restorable"

    def test_restore_pending_obligation_fails(self):
        """PENDING 状态的义务不能恢复（还没过期）"""
        engine = make_test_engine()
        now = time.time()

        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_pending",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now + 100,  # 还未到期
            status=ObligationStatus.PENDING,
            created_at=now - 50,
            updated_at=now,
        )
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert not result.success
        assert result.failure_reason == "not_restorable"

    def test_restore_cancelled_obligation_fails(self):
        """CANCELLED 状态的义务不能恢复"""
        engine = make_test_engine()
        now = time.time()

        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_cancelled",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now - 10,
            status=ObligationStatus.CANCELLED,
            created_at=now - 110,
            updated_at=now,
        )
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert not result.success
        assert result.failure_reason == "not_restorable"


class TestRestoreValidation:
    """测试恢复操作的其他验证逻辑"""

    def test_restore_not_found_obligation(self):
        """不存在的 obligation_id 返回 not_found"""
        engine = make_test_engine()

        result = engine.restore_obligation(
            obligation_id="nonexistent_id",
            actor_id="test_agent",
        )

        assert not result.success
        assert result.failure_reason == "not_found"

    def test_restore_wrong_actor_fails(self):
        """actor_id 不匹配时不能恢复"""
        engine = make_test_engine()
        ob = make_expired_obligation(engine, overdue_secs=5.0)

        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id="wrong_actor",  # 不是 ob.actor_id
        )

        assert not result.success
        assert result.failure_reason == "wrong_actor"

    def test_restore_escalated_obligation_success(self):
        """ESCALATED 状态的义务可以恢复"""
        engine = make_test_engine()
        now = time.time()

        deadline_duration = 100.0
        ob = ObligationRecord(
            obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
            entity_id="test_entity_escalated",
            actor_id="test_agent",
            obligation_type="test_required_action",
            required_event_types=["action_completed"],
            due_at=now - 20.0,
            status=ObligationStatus.ESCALATED,
            escalated=True,
            escalated_at=now - 10,
            restoration_grace_period_multiplier=2.0,
            created_at=now - 120.0,
            updated_at=now,
        )
        engine.store.add_obligation(ob)

        result = engine.restore_obligation(
            obligation_id=ob.obligation_id,
            actor_id=ob.actor_id,
        )

        assert result.success
        ob_restored = engine.store.get_obligation(ob.obligation_id)
        assert ob_restored.status == ObligationStatus.RESTORED


class TestRestorationDeadlineCalculation:
    """测试恢复截止时间的计算逻辑"""

    def test_restoration_deadline_default_multiplier(self):
        """默认 multiplier=2.0 的恢复期计算"""
        now = time.time()
        deadline_duration = 100.0

        ob = ObligationRecord(
            obligation_id="test_ob",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="test_action",
            required_event_types=["action_completed"],
            due_at=now,
            restoration_grace_period_multiplier=2.0,
            created_at=now - deadline_duration,
            updated_at=now,
        )

        # restoration_deadline = due_at + (deadline_duration * multiplier)
        #                     = now + (100 * 2.0)
        #                     = now + 200
        expected = now + 200.0
        assert abs(ob.restoration_deadline() - expected) < 1.0

    def test_restoration_deadline_custom_multiplier(self):
        """自定义 multiplier=3.0 的恢复期计算"""
        now = time.time()
        deadline_duration = 50.0

        ob = ObligationRecord(
            obligation_id="test_ob",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="test_action",
            required_event_types=["action_completed"],
            due_at=now,
            restoration_grace_period_multiplier=3.0,
            created_at=now - deadline_duration,
            updated_at=now,
        )

        # restoration_deadline = due_at + (deadline_duration * multiplier)
        #                     = now + (50 * 3.0)
        #                     = now + 150
        expected = now + 150.0
        assert abs(ob.restoration_deadline() - expected) < 1.0

    def test_restoration_deadline_no_due_at(self):
        """没有 due_at 时 restoration_deadline() 返回 None"""
        ob = ObligationRecord(
            obligation_id="test_ob",
            entity_id="test_entity",
            actor_id="test_agent",
            obligation_type="test_action",
            required_event_types=["action_completed"],
            due_at=None,  # 无截止时间
            created_at=time.time(),
        )

        assert ob.restoration_deadline() is None
        assert not ob.can_restore()
