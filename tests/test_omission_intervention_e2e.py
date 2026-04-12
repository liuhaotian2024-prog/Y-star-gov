"""
test_omission_intervention_e2e.py — End-to-End Omission→Intervention Tests
===========================================================================

验证 OmissionEngine.scan() → violations → InterventionEngine.process_violations()
→ InterventionPulse → capability restrictions 的完整链路。

这是 Governance Engineer 的 Proactive Trigger 要求：
"OmissionEngine scan→pulse chain not verified end-to-end → write chaos test"

测试覆盖：
  1. scan() 检测 soft_overdue → InterventionEngine 产生 soft pulse
  2. scan() 检测 hard_overdue → InterventionEngine 产生 interrupt gate
  3. gate_check() 阻止 hard_overdue actor 执行高风险动作
  4. gate_check() 允许 hard_overdue actor 履行义务
  5. resolve_for_actor() 解除干预后 actor 恢复权限
"""
import time
import uuid

import pytest

from ystar.governance.omission_store import InMemoryOmissionStore
from ystar.governance.omission_engine import OmissionEngine
from ystar.governance.omission_models import (
    TrackedEntity, GovernanceEvent, GEventType,
    EntityStatus, ObligationStatus, ObligationRecord, Severity,
)
from ystar.governance.omission_rules import get_registry
from ystar.governance.intervention_engine import (
    InterventionEngine, DEFAULT_GATING_POLICY,
)
from ystar.governance.intervention_models import InterventionLevel, GateDecision
from ystar.governance.cieu_store import NullCIEUStore


# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def omission_intervention_system():
    """
    创建一个完整的 Omission + Intervention 系统用于测试。
    返回: (omission_engine, intervention_engine, store, now_fn)
    """
    store = InMemoryOmissionStore()
    registry = get_registry()
    cieu_store = NullCIEUStore(silent=True)

    # 可控时间（测试需要模拟时间流逝）
    fake_time = [time.time()]
    def now_fn():
        return fake_time[0]

    omission_engine = OmissionEngine(
        store=store,
        registry=registry,
        cieu_store=cieu_store,
        now_fn=now_fn,
    )

    intervention_engine = InterventionEngine(
        omission_store=store,
        cieu_store=cieu_store,
        now_fn=now_fn,
        soft_pulse_on_soft_overdue=True,
        interrupt_gate_on_hard_overdue=True,
        reroute_on_escalated=True,
        gating_policy=DEFAULT_GATING_POLICY,
    )

    return omission_engine, intervention_engine, store, fake_time


# ── Test 1: scan() → soft_overdue → soft pulse ──────────────────────────────


def test_scan_soft_overdue_produces_soft_pulse(omission_intervention_system):
    """
    验证 OmissionEngine.scan() 检测到 soft_overdue 后，
    InterventionEngine.process_violations() 能产生 soft pulse。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # Step 1: 创建 entity 和 obligation
    entity = TrackedEntity(
        entity_id="task_001",
        entity_type="task",
        current_owner_id="agent_a",
        initiator_id="system",
        status=EntityStatus.ACTIVE,
    )
    omission_engine.register_entity(entity)

    obligation = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        obligation_type="acknowledgement",
        entity_id="task_001",
        actor_id="agent_a",
        status=ObligationStatus.PENDING,
        due_at=fake_time[0] + 60.0,  # 60秒后到期
        hard_overdue_secs=120.0,     # hard threshold = due_at + 120s
        severity=Severity.MEDIUM,
    )
    store.add_obligation(obligation)

    # Step 2: 时间流逝，超过 due_at（进入 soft_overdue）
    fake_time[0] += 70.0  # 超过 due_at 10秒

    # Step 3: scan() 检测 soft_overdue
    result = omission_engine.scan(now=fake_time[0])

    assert len(result.violations) == 1, "应该检测到1个 soft violation"
    assert len(result.expired) == 1, "应该有1个 expired obligation"
    violation = result.violations[0]
    assert violation.obligation_id == obligation.obligation_id

    # Step 4: InterventionEngine.process_violations() 产生 soft pulse
    int_result = intervention_engine.process_violations(result.violations)

    assert len(int_result.pulses_fired) >= 1, "应该产生至少1个 intervention pulse"
    pulses = intervention_engine.pulse_store.active_pulses_for_entity("task_001")
    assert len(pulses) >= 1, "entity 应该有至少1个 active pulse"

    soft_pulses = [p for p in pulses if p.level == InterventionLevel.SOFT_PULSE]
    assert len(soft_pulses) >= 1, "应该有 soft pulse"


# ── Test 2: scan() → hard_overdue → interrupt gate ──────────────────────────


def test_scan_hard_overdue_produces_interrupt_gate(omission_intervention_system):
    """
    验证 OmissionEngine.scan() 检测到 hard_overdue 后，
    InterventionEngine.process_violations() 能产生 interrupt gate。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # Step 1: 创建 entity 和 obligation
    entity = TrackedEntity(
        entity_id="task_002",
        entity_type="task",
        current_owner_id="agent_b",
        initiator_id="system",
        status=EntityStatus.ACTIVE,
    )
    omission_engine.register_entity(entity)

    obligation = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        obligation_type="status_update",
        entity_id="task_002",
        actor_id="agent_b",
        status=ObligationStatus.PENDING,
        due_at=fake_time[0] + 60.0,
        hard_overdue_secs=120.0,
        severity=Severity.HIGH,
    )
    store.add_obligation(obligation)

    # Step 2: 先进入 soft_overdue
    fake_time[0] += 70.0
    result1 = omission_engine.scan(now=fake_time[0])
    assert len(result1.violations) == 1

    # Step 3: 继续时间流逝，超过 hard threshold
    fake_time[0] += 130.0  # 总共超过 due_at 200秒 (> 120s hard threshold)
    result2 = omission_engine.scan(now=fake_time[0])

    # 应该产生 hard violation
    hard_violations = [v for v in result2.violations if v.details.get("stage") == "hard_overdue"]
    assert len(hard_violations) >= 1, "应该检测到 hard_overdue violation"

    # Step 4: InterventionEngine.process_violations() 产生 interrupt gate
    int_result = intervention_engine.process_violations(result2.violations)

    pulses = intervention_engine.pulse_store.active_pulses_for_entity("task_002")
    interrupt_pulses = [p for p in pulses if p.level == InterventionLevel.INTERRUPT_GATE]
    assert len(interrupt_pulses) >= 1, "应该有 interrupt gate pulse"


# ── Test 3: gate_check() 阻止 hard_overdue actor 执行高风险动作 ─────────────


def test_gate_check_blocks_high_risk_action_on_hard_overdue(omission_intervention_system):
    """
    验证 gate_check() 在 actor 有 hard_overdue obligation 时，
    阻止高风险动作（如 ENTITY_CREATED）。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # Step 1: 创建 hard_overdue obligation
    entity = TrackedEntity(
        entity_id="task_003",
        entity_type="task",
        current_owner_id="agent_c",
        initiator_id="system",
        status=EntityStatus.ACTIVE,
    )
    omission_engine.register_entity(entity)

    obligation = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        obligation_type="acknowledgement",
        entity_id="task_003",
        actor_id="agent_c",
        status=ObligationStatus.HARD_OVERDUE,  # 直接设为 hard_overdue
        due_at=fake_time[0] - 200.0,           # 已经过期200秒
        hard_violation_at=fake_time[0] - 50.0,
        severity=Severity.CRITICAL,
    )
    store.add_obligation(obligation)

    # Step 2: InterventionEngine 处理（产生 interrupt gate）
    # 先创建一个 violation 来触发
    from ystar.governance.omission_models import OmissionViolation, OmissionType
    violation = OmissionViolation(
        violation_id=f"v_{uuid.uuid4().hex[:8]}",
        entity_id="task_003",
        obligation_id=obligation.obligation_id,
        omission_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT,
        detected_at=fake_time[0],
        actor_id="agent_c",
        severity=Severity.CRITICAL,
        details={"stage": "hard_overdue"},
    )

    int_result = intervention_engine.process_violations([violation])
    assert len(int_result.pulses_fired) >= 1

    # Step 3: gate_check() 高风险动作（ENTITY_CREATED）
    gate_result = intervention_engine.gate_check(
        actor_id="agent_c",
        action_type=GEventType.ENTITY_CREATED,  # 高风险动作
    )

    assert gate_result.decision == GateDecision.DENY, "应该 DENY 高风险动作"
    # reason may be the omission_type string (e.g. "acknowledgement") or contain "overdue"/"obligation"
    reason_lower = gate_result.reason.lower()
    assert any(kw in reason_lower for kw in ("overdue", "obligation", "acknowledgement")), \
        f"reason should indicate blocking cause, got: {gate_result.reason}"


# ── Test 4: gate_check() 允许 hard_overdue actor 履行义务 ───────────────────


def test_gate_check_allows_fulfillment_action_on_hard_overdue(omission_intervention_system):
    """
    验证 gate_check() 在 actor 有 hard_overdue obligation 时，
    仍然允许履行义务的动作（如 ACKNOWLEDGEMENT_EVENT）。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # 复用上一个测试的 hard_overdue 场景
    entity = TrackedEntity(
        entity_id="task_004",
        entity_type="task",
        current_owner_id="agent_d",
        initiator_id="system",
        status=EntityStatus.ACTIVE,
    )
    omission_engine.register_entity(entity)

    obligation = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        obligation_type="acknowledgement",
        entity_id="task_004",
        actor_id="agent_d",
        status=ObligationStatus.HARD_OVERDUE,
        due_at=fake_time[0] - 200.0,
        hard_violation_at=fake_time[0] - 50.0,
        severity=Severity.CRITICAL,
    )
    store.add_obligation(obligation)

    from ystar.governance.omission_models import OmissionViolation, OmissionType
    violation = OmissionViolation(
        violation_id=f"v_{uuid.uuid4().hex[:8]}",
        entity_id="task_004",
        obligation_id=obligation.obligation_id,
        omission_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT,
        detected_at=fake_time[0],
        actor_id="agent_d",
        severity=Severity.CRITICAL,
        details={"stage": "hard_overdue"},
    )

    intervention_engine.process_violations([violation])

    # gate_check() 履行义务的动作（ACKNOWLEDGEMENT_EVENT）
    gate_result = intervention_engine.gate_check(
        actor_id="agent_d",
        action_type=GEventType.ACKNOWLEDGEMENT_EVENT,  # 履行义务动作
    )

    assert gate_result.decision == GateDecision.ALLOW, "应该 ALLOW 履行义务的动作"


# ── Test 5: resolve_for_actor() 解除干预后恢复权限 ──────────────────────────


def test_resolve_for_actor_restores_capabilities(omission_intervention_system):
    """
    验证 resolve_for_actor() 在 actor 履行义务后，
    能解除干预并恢复 actor 的权限。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # Step 1: 创建 hard_overdue obligation 和 restriction
    entity = TrackedEntity(
        entity_id="task_005",
        entity_type="task",
        current_owner_id="agent_e",
        initiator_id="system",
        status=EntityStatus.ACTIVE,
    )
    omission_engine.register_entity(entity)

    obligation = ObligationRecord(
        obligation_id=f"ob_{uuid.uuid4().hex[:8]}",
        obligation_type="acknowledgement",
        entity_id="task_005",
        actor_id="agent_e",
        status=ObligationStatus.HARD_OVERDUE,
        due_at=fake_time[0] - 200.0,
        hard_violation_at=fake_time[0] - 50.0,
        severity=Severity.CRITICAL,
        required_event_types=[GEventType.ACKNOWLEDGEMENT_EVENT],
    )
    store.add_obligation(obligation)

    from ystar.governance.omission_models import OmissionViolation, OmissionType
    violation = OmissionViolation(
        violation_id=f"v_{uuid.uuid4().hex[:8]}",
        entity_id="task_005",
        obligation_id=obligation.obligation_id,
        omission_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT,
        detected_at=fake_time[0],
        actor_id="agent_e",
        severity=Severity.CRITICAL,
        details={"stage": "hard_overdue"},
    )

    intervention_engine.process_violations([violation])

    # 验证 restriction 存在
    restriction = intervention_engine.pulse_store.get_restriction("agent_e")
    assert restriction is not None, "应该有 capability restriction"
    assert restriction.active is True

    # Step 2: actor 履行义务（发送 ACKNOWLEDGEMENT_EVENT）
    ack_event = GovernanceEvent(
        event_type=GEventType.ACKNOWLEDGEMENT_EVENT,
        entity_id="task_005",
        actor_id="agent_e",
        ts=fake_time[0],
    )
    fulfill_result = omission_engine.ingest_event(ack_event)
    assert len(fulfill_result.fulfilled) >= 1, "义务应该被履行"

    # Step 3: resolve_for_actor() 解除干预
    resolved_pulses = intervention_engine.resolve_for_actor(
        actor_id="agent_e",
        fulfilled_obligation_id=obligation.obligation_id,
    )

    assert len(resolved_pulses) >= 1, "应该解除至少1个 pulse"

    # Step 4: 验证 restriction 已解除
    restriction_after = intervention_engine.pulse_store.get_restriction("agent_e")
    assert restriction_after is None, "restriction 应该已解除"

    # Step 5: gate_check() 应该再次允许高风险动作
    gate_result = intervention_engine.gate_check(
        actor_id="agent_e",
        action_type=GEventType.ENTITY_CREATED,
    )

    assert gate_result.decision == GateDecision.ALLOW, "权限恢复后应该 ALLOW"


# ── Test 6: Chaos — 大量并发 violations 处理 ────────────────────────────────


def test_chaos_concurrent_violations(omission_intervention_system):
    """
    混沌测试：大量并发 violations 涌入 InterventionEngine，
    验证系统不会崩溃或产生数据不一致。
    """
    omission_engine, intervention_engine, store, fake_time = omission_intervention_system

    # 创建20个 entities 和 obligations (below circuit breaker threshold of 50)
    violations = []
    for i in range(20):
        entity = TrackedEntity(
            entity_id=f"task_{i:03d}",
            entity_type="task",
            current_owner_id=f"agent_{i % 10}",  # 10个不同的 agents
            initiator_id="system",
            status=EntityStatus.ACTIVE,
        )
        omission_engine.register_entity(entity)

        obligation = ObligationRecord(
            obligation_id=f"ob_{i:03d}",
            obligation_type="acknowledgement",
            entity_id=f"task_{i:03d}",
            actor_id=f"agent_{i % 10}",
            status=ObligationStatus.HARD_OVERDUE,
            due_at=fake_time[0] - 200.0,
            hard_violation_at=fake_time[0] - 50.0,
            severity=Severity.HIGH if i % 3 == 0 else Severity.MEDIUM,
        )
        store.add_obligation(obligation)

        from ystar.governance.omission_models import OmissionViolation, OmissionType
        violation = OmissionViolation(
            violation_id=f"v_{i:03d}",
            entity_id=f"task_{i:03d}",
            obligation_id=f"ob_{i:03d}",
            omission_type=OmissionType.REQUIRED_ACKNOWLEDGEMENT,
            detected_at=fake_time[0],
            actor_id=f"agent_{i % 10}",
            severity=obligation.severity,
            details={"stage": "hard_overdue"},
        )
        violations.append(violation)

    # 批量处理所有 violations
    int_result = intervention_engine.process_violations(violations)

    assert len(int_result.pulses_fired) >= 10, "应该产生大量 pulses（至少每个 agent 1个）"

    # 验证每个 agent 都有 restriction
    for i in range(10):
        restriction = intervention_engine.pulse_store.get_restriction(f"agent_{i}")
        assert restriction is not None, f"agent_{i} 应该有 restriction"

    # 验证所有 pulses 都是 active
    all_pulses = intervention_engine.pulse_store.all_pulses()
    active_pulses = [p for p in all_pulses if p.status.value == "active"]
    assert len(active_pulses) >= 10, "应该有大量 active pulses"
