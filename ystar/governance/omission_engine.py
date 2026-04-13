# Layer: Foundation
"""
ystar.omission_engine  —  Deterministic Omission Governance Engine
==================================================================

这是防消极层的"心脏"。

两个核心职责：
  1. 事件驱动：接收 GovernanceEvent → 触发新 obligation / 履行已有 obligation
  2. 时间扫描：扫描 pending obligations → 检测过期 → 产出 OmissionViolation

设计原则：
  - 完全 deterministic：同 store 状态 + 同时间点 = 同输出
  - 不做推理，只做核查
  - 幂等性：重复调用 scan() 不会重复创建违规记录
  - CIEU 兼容：violation 可选写入 CIEUStore

使用方式：
    from ystar.governance.omission_engine import OmissionEngine
    from ystar.governance.omission_store import InMemoryOmissionStore
    from ystar.governance.omission_rules import get_registry

    engine = OmissionEngine(store=InMemoryOmissionStore(), registry=get_registry())

    # 注入事件
    engine.ingest_event(ev)

    # 扫描过期义务（定时调用）
    violations = engine.scan()
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ystar.governance.omission_models import (
    EntityStatus, ObligationStatus, Severity,
    EscalationAction, EscalationPolicy,
    TrackedEntity, ObligationRecord, GovernanceEvent,
    OmissionViolation, GEventType, OmissionType,
    RestorationResult,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore
from ystar.governance.omission_rules import RuleRegistry, get_registry
from ystar.governance.cieu_store import NullCIEUStore

_log = logging.getLogger(__name__)

# 类型别名：支持两种 store
AnyStore = Union[InMemoryOmissionStore, OmissionStore]


# ── 引擎输出 ─────────────────────────────────────────────────────────────────

@dataclass
class EngineResult:
    """一次 scan() 或 ingest_event() 的输出摘要。"""
    new_obligations:   List[ObligationRecord]   = field(default_factory=list)
    fulfilled:         List[ObligationRecord]   = field(default_factory=list)
    expired:           List[ObligationRecord]   = field(default_factory=list)
    violations:        List[OmissionViolation]  = field(default_factory=list)
    reminders:         List[ObligationRecord]   = field(default_factory=list)
    escalated:         List[OmissionViolation]  = field(default_factory=list)

    def is_clean(self) -> bool:
        return len(self.violations) == 0 and len(self.expired) == 0

    def summary(self) -> str:
        parts = []
        if self.new_obligations:
            parts.append(f"+{len(self.new_obligations)} obligations")
        if self.fulfilled:
            parts.append(f"{len(self.fulfilled)} fulfilled")
        if self.expired:
            parts.append(f"{len(self.expired)} EXPIRED")
        if self.violations:
            parts.append(f"{len(self.violations)} VIOLATIONS")
        if self.reminders:
            parts.append(f"{len(self.reminders)} reminders")
        if self.escalated:
            parts.append(f"{len(self.escalated)} ESCALATED")
        return " | ".join(parts) if parts else "clean"


# ── OmissionEngine ───────────────────────────────────────────────────────────

class OmissionEngine:
    """
    Deterministic omission governance engine。

    参数：
        store:     obligation / event / violation 存储后端
        registry:  规则注册表（内置 7 条通用规则 + domain pack 扩展）
        cieu_store:可选 CIEUStore（violation 写入证据链）
        now_fn:    时间函数（测试时可注入假时间）
    """

    def __init__(
        self,
        store: AnyStore = None,
        registry: Optional[RuleRegistry] = None,
        cieu_store: Any = None,          # CIEUStore | NullCIEUStore | None
        now_fn: Optional[Any] = None,    # Callable[[], float]
        causal_notify_fn: Optional[Any] = None,  # GAP 5: Callable[[dict], None]
        trigger_registry: Any = None,    # TriggerRegistry | None
    ) -> None:
        # GOV-010 Phase 1: default to persistent SQLite store instead of
        # requiring callers to pass InMemoryOmissionStore explicitly.
        # Obligations now survive process exit.
        if store is None:
            store = OmissionStore(db_path=".ystar_omission.db")
        self.store    = store
        self.registry = registry or get_registry()
        # [FIX-2] 用 NullCIEUStore 替代 None 作为默认值。
        # None 会导致 omission 违规静默丢失（_write_to_cieu 直接 return）。
        # NullCIEUStore 保持接口一致，同时发出 UserWarning 提醒配置缺失。
        self.cieu_store = cieu_store if cieu_store is not None else NullCIEUStore()
        self._now     = now_fn or time.time
        # GAP 5 FIX: Push model — notify causal engine of violations
        self._causal_notify_fn = causal_notify_fn
        # P2-2: Automatic obligation trigger activation
        # Import here to avoid circular dependency
        if trigger_registry is None:
            try:
                from ystar.governance.obligation_triggers import get_trigger_registry
                self.trigger_registry = get_trigger_registry()
            except ImportError:
                # Optional import — trigger system is not yet available
                self.trigger_registry = None
        else:
            self.trigger_registry = trigger_registry

    # ── 主入口 1：注入单个事件 ───────────────────────────────────────────────

    def ingest_event(self, ev: GovernanceEvent) -> EngineResult:
        """
        接收一个 GovernanceEvent：
          1. 存入 store
          2. 检查是否 fulfill 了任何 pending obligation
          3. 检查是否触发了新的 obligation（通过 rule matching）
          4. P2-2: 检查是否匹配 ObligationTrigger（自动触发）
          5. 返回 EngineResult
        """
        result = EngineResult()

        # 1. 持久化事件
        self.store.add_event(ev)

        # 2. 尝试 fulfill pending obligations
        fulfilled = self._try_fulfill(ev)
        result.fulfilled.extend(fulfilled)

        # 3. 触发新 obligation（rule matching）
        new_obs = self._trigger_obligations(ev)
        result.new_obligations.extend(new_obs)

        # 4. P2-2: Automatic obligation trigger activation
        # When a tool_call event is ingested with ALLOW decision,
        # check if it matches any ObligationTriggers
        if ev.event_type == "tool_call":
            trigger_obs = self._match_and_create_trigger_obligations(ev)
            result.new_obligations.extend(trigger_obs)

        return result

    # ── 主入口 2：时间扫描（定时调用）─────────────────────────────────────────

    def scan(self, now: Optional[float] = None) -> EngineResult:
        """
        扫描所有 pending obligations，检测过期，产出 violations / reminders / escalations。
        同时扫描已 EXPIRED 但未升级的 obligations，补充升级动作。
        幂等：对已有 violation 的 obligation 不重复创建。
        """
        now = now or self._now()
        result = EngineResult()

        pending = self.store.pending_obligations()

        for ob in pending:
            # 检查是否应发 reminder
            if self._should_remind(ob, now):
                ob.reminder_sent_at = now
                self.store.update_obligation(ob)
                result.reminders.append(ob)

            if not ob.is_overdue(now):
                continue

            # ── v0.33 Aging: Soft → Hard 双阶段超时 ──────────────────────
            # 阶段 1: SOFT_OVERDUE（首次越过 due_at）
            if ob.status == ObligationStatus.PENDING:
                ob.status           = ObligationStatus.SOFT_OVERDUE
                ob.soft_violation_at = now
                ob.soft_count       += 1
                # soft severity 升级：每次 soft_count +1 时提升
                if ob.soft_count >= 3 and ob.severity == Severity.LOW:
                    ob.severity = Severity.MEDIUM
                elif ob.soft_count >= 2 and ob.severity == Severity.MEDIUM:
                    ob.severity = Severity.HIGH
                self.store.update_obligation(ob)
                # 创建 soft violation（幂等）
                # Gate: only fire if entity is active (fix for timer-fired violation noise)
                if not self.store.violation_exists_for_obligation(ob.obligation_id):
                    if self._is_entity_active(ob.entity_id, now):
                        overdue_secs = now - (ob.effective_due_at or now)
                        v = self._create_violation(ob, now, overdue_secs)
                        self.store.add_violation(v)
                        self._write_to_cieu(ob, v)
                        result.violations.append(v)
                result.expired.append(ob)  # 兼容性：expired 列表仍包含 soft overdue
                self._update_entity_on_violation(ob)

            # 阶段 2: HARD_OVERDUE（超过 due_at + hard_overdue_secs）
            elif ob.status == ObligationStatus.SOFT_OVERDUE:
                hard_threshold = (ob.effective_due_at or now) + ob.hard_overdue_secs
                if now >= hard_threshold:
                    ob.status          = ObligationStatus.HARD_OVERDUE
                    ob.hard_violation_at = now
                    # hard overdue 强制提升到 HIGH/CRITICAL
                    if ob.severity == Severity.LOW:
                        ob.severity = Severity.MEDIUM
                    elif ob.severity == Severity.MEDIUM:
                        ob.severity = Severity.HIGH
                    self.store.update_obligation(ob)
                    # hard violation（独立幂等 key = obligation_id + "_hard"）
                    # Gate: only fire if entity is active
                    if not self._hard_violation_exists(ob.obligation_id):
                        if self._is_entity_active(ob.entity_id, now):
                            overdue_secs = now - (ob.effective_due_at or now)
                            v = self._create_violation(ob, now, overdue_secs)
                            v.details["stage"] = "hard_overdue"
                            self.store.add_violation(v)
                            self._write_to_cieu(ob, v)
                            result.violations.append(v)
                    # 升级处理
                    if self._should_escalate(ob, now):
                        viols = self.store.list_violations(entity_id=ob.entity_id)
                        v = next((x for x in viols if x.obligation_id == ob.obligation_id), None)
                        if v:
                            v = self._escalate(ob, v, now)
                            self.store.update_violation(v)
                            result.escalated.append(v)
                    self._update_entity_on_violation(ob)

            elif ob.status == ObligationStatus.PENDING:
                # Legacy path（soft/hard 之前的老 obligation）
                # Gate: only fire if entity is active
                if not self.store.violation_exists_for_obligation(ob.obligation_id):
                    if self._is_entity_active(ob.entity_id, now):
                        ob.status = ObligationStatus.EXPIRED
                        self.store.update_obligation(ob)
                        overdue_secs = now - (ob.effective_due_at or now)
                        v = self._create_violation(ob, now, overdue_secs)
                        self.store.add_violation(v)
                        self._write_to_cieu(ob, v)
                        result.violations.append(v)
                        result.expired.append(ob)

        # 二次扫描 A: SOFT_OVERDUE → HARD_OVERDUE promotion
        for ob in self.store.list_obligations(status=ObligationStatus.SOFT_OVERDUE):
            if ob.hard_overdue_secs <= 0:
                continue
            hard_threshold = (ob.effective_due_at or now) + ob.hard_overdue_secs
            if now < hard_threshold:
                continue
            if ob.status != ObligationStatus.SOFT_OVERDUE:
                continue
            ob.status           = ObligationStatus.HARD_OVERDUE
            ob.hard_violation_at = now
            if ob.severity == Severity.LOW:
                ob.severity = Severity.MEDIUM
            elif ob.severity == Severity.MEDIUM:
                ob.severity = Severity.HIGH
            self.store.update_obligation(ob)
            # Gate: only fire if entity is active
            if not self._hard_violation_exists(ob.obligation_id):
                if self._is_entity_active(ob.entity_id, now):
                    overdue_secs = now - (ob.effective_due_at or now)
                    v = self._create_violation(ob, now, overdue_secs)
                    v.details["stage"] = "hard_overdue"
                    self.store.add_violation(v)
                    self._write_to_cieu(ob, v)
                    result.violations.append(v)
            if self._should_escalate(ob, now):
                violations_for_ob = self.store.list_violations(entity_id=ob.entity_id)
                v_ob = next((x for x in violations_for_ob
                             if x.obligation_id == ob.obligation_id), None)
                if v_ob:
                    v_ob = self._escalate(ob, v_ob, now)
                    self.store.update_violation(v_ob)
                    result.escalated.append(v_ob)
            self._update_entity_on_violation(ob)

        # 二次扫描 B: SOFT_OVERDUE 的跨周期升级检查（escalate_after_secs 到达时）
        for ob in self.store.list_obligations(status=ObligationStatus.SOFT_OVERDUE):
            if ob.escalated:
                continue
            if not self._should_escalate(ob, now):
                continue
            violations_ob = self.store.list_violations(entity_id=ob.entity_id)
            v_ob = next((x for x in violations_ob if x.obligation_id == ob.obligation_id), None)
            if v_ob is None:
                continue
            v_ob = self._escalate(ob, v_ob, now)
            self.store.update_violation(v_ob)
            result.escalated.append(v_ob)

        return result

    def _scan_obligation_type(self, obligation_type: str) -> EngineResult:
        """
        Live-reload scan: immediately scan for obligations of a newly registered type.

        Called by TriggerRegistry.register() when a new trigger is added with engine parameter.
        Scans all entities' recent events to see if any should retroactively create obligations.

        Args:
            obligation_type: The newly registered obligation type to scan for

        Returns:
            EngineResult with any newly created obligations
        """
        result = EngineResult()
        now = self._now()

        # Get all triggers for this obligation type
        if self.trigger_registry is None:
            return result

        matching_triggers = [
            t for t in self.trigger_registry.all_enabled()
            if t.obligation_type == obligation_type
        ]

        if not matching_triggers:
            return result

        # Collect all events from all tracked entities
        # (InMemoryOmissionStore/OmissionStore don't have list_events(), only events_for_entity)
        all_entities = self.store.list_entities()
        all_events = []
        for entity in all_entities:
            # Get recent events for this entity (last 100 per entity to limit scan cost)
            entity_events = self.store.events_for_entity(entity.entity_id)
            # Manually limit to last 100 events per entity
            all_events.extend(entity_events[-100:] if len(entity_events) > 100 else entity_events)

        for ev in all_events:
            # Only check tool_call events (triggers only fire on tool calls)
            if ev.event_type != "tool_call":
                continue

            payload = ev.payload or {}
            tool_name = payload.get("tool_name")
            tool_input = payload.get("tool_input", {})
            decision = payload.get("decision", "ALLOW")

            # Only ALLOW decisions create obligations (DENY handled separately)
            if decision != "ALLOW" or not tool_name:
                continue

            # Check if this event matches any of the new triggers
            for trigger in matching_triggers:
                if not trigger.matches_tool(tool_name):
                    continue
                if not trigger.matches_params(tool_input):
                    continue

                # Found a match - create obligation if not already exists
                target_actor = trigger.get_target_actor(ev.actor_id)

                # Deduplicate: check if same type already pending for this entity+actor
                if trigger.deduplicate:
                    existing = self.store.list_obligations(
                        entity_id=ev.entity_id,
                        status=ObligationStatus.PENDING
                    )
                    if any(
                        ob.obligation_type == trigger.obligation_type
                        and ob.actor_id == target_actor
                        for ob in existing
                    ):
                        continue  # Skip duplicate

                # Create new obligation from trigger
                ob = ObligationRecord(
                    obligation_id=str(uuid.uuid4()),
                    entity_id=ev.entity_id,
                    obligation_type=trigger.obligation_type,
                    actor_id=target_actor,
                    triggered_by_event_id=ev.event_id,
                    created_at=ev.ts,  # Use original event time
                    due_at=ev.ts + trigger.deadline_seconds,
                    effective_due_at=ev.ts + trigger.deadline_seconds,
                    status=ObligationStatus.PENDING,
                    severity=Severity[trigger.severity],
                    required_event_types=trigger.required_event_types or [trigger.fulfillment_event],
                    description=trigger.description,
                    grace_period_secs=trigger.grace_period_secs,
                    hard_overdue_secs=trigger.hard_overdue_secs,
                    escalation_policy=EscalationPolicy(
                        escalate_to_hard=trigger.escalate_to_hard,
                        escalate_after_secs=trigger.hard_overdue_secs,
                        escalate_to_actor=trigger.escalate_to_actor,
                        deny_closure_on_open=trigger.deny_closure_on_open,
                    ),
                )
                self.store.add_obligation(ob)
                result.new_obligations.append(ob)

                _log.info(
                    f"[OmissionEngine] Live-reload: created {obligation_type} obligation "
                    f"for retroactive event {ev.event_id[:8]}"
                )
            self.store.update_violation(v_ob)
            result.escalated.append(v_ob)

        # 二次扫描 C: 已 EXPIRED 但尚未升级的 obligation（跨 scan 周期的迟到升级）
        for ob in self.store.list_obligations(status=ObligationStatus.EXPIRED):
            if ob.escalated:
                continue
            if not self._should_escalate(ob, now):
                continue
            violations = self.store.list_violations(entity_id=ob.entity_id)
            v = next((x for x in violations if x.obligation_id == ob.obligation_id), None)
            if v is None:
                continue
            v = self._escalate(ob, v, now)
            self.store.update_violation(v)
            result.escalated.append(v)

        # GAP 5 FIX: Push violations to causal engine via callback
        if self._causal_notify_fn and result.violations:
            for v in result.violations:
                try:
                    self._causal_notify_fn({
                        "violation_id":  v.violation_id,
                        "entity_id":     v.entity_id,
                        "actor_id":      v.actor_id,
                        "omission_type": v.omission_type,
                        "overdue_secs":  v.overdue_secs,
                        "severity":      v.severity.value if hasattr(v.severity, 'value') else str(v.severity),
                        "detected_at":   v.detected_at,
                    })
                except Exception as e:
                    _log.warning("Failed to serialize violation for event %s: %s", event.event_type, e)

        return result

    # ── 实体管理 ─────────────────────────────────────────────────────────────

    def register_entity(self, entity: TrackedEntity) -> None:
        """注册新实体（由 adapter 调用）。"""
        self.store.upsert_entity(entity)

    def update_entity_status(
        self,
        entity_id: str,
        new_status: EntityStatus,
        actor_id: str = "system",
    ) -> Optional[TrackedEntity]:
        entity = self.store.get_entity(entity_id)
        if entity is None:
            return None
        entity.status = new_status
        entity.touch()
        self.store.upsert_entity(entity)
        return entity

    def can_close(self, entity_id: str) -> bool:
        """
        检查某 entity 是否可以安全 close。

        拒绝条件（任一满足即不可 close）：
          1. 有 deny_closure_on_open 的 obligation 仍为 PENDING
          2. 有 deny_closure_on_open 的 obligation 已 EXPIRED（即发生了 violation）
             —— violation 本身未解决，不允许悄悄 close
        """
        for ob in self.store.list_obligations(entity_id=entity_id):
            if ob.status.is_open and ob.escalation_policy.deny_closure_on_open:
                return False
            # ESCALATED also blocks closure
            if ob.status == ObligationStatus.ESCALATED and ob.escalation_policy.deny_closure_on_open:
                return False
        return True

    # ── 私有：fulfill ─────────────────────────────────────────────────────────

    def _hard_violation_exists(self, obligation_id: str) -> bool:
        """检查是否已有 hard_overdue stage 的 violation（幂等保护）。"""
        viols = self.store.list_violations()
        return any(
            v.obligation_id == obligation_id
            and v.details.get("stage") == "hard_overdue"
            for v in viols
        )

    def _try_fulfill(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        检查新事件是否能履行某些 open obligations。
        匹配条件：entity_id 相同 + event_type 在 required_event_types 中。
        v0.33: 扩展到 PENDING / SOFT_OVERDUE / HARD_OVERDUE 状态。
        v0.50: Auto-fulfillment via fulfiller event pattern matching (AMENDMENT-012)
        """
        fulfilled = []
        # check all open-status obligations (PENDING + SOFT_OVERDUE + HARD_OVERDUE)
        all_obs = self.store.list_obligations(entity_id=ev.entity_id)
        for ob in all_obs:
            if not ob.status.is_open:
                continue

            # Original fulfillment: exact event_type match
            if ev.event_type in ob.required_event_types:
                ob.status = ObligationStatus.FULFILLED
                ob.fulfilled_by_event_id = ev.event_id
                self.store.update_obligation(ob)
                fulfilled.append(ob)
                continue

            # v0.50: Auto-fulfillment via fulfiller pattern matching
            if self._matches_fulfiller_pattern(ob, ev):
                ob.status = ObligationStatus.FULFILLED
                ob.fulfilled_by_event_id = ev.event_id
                self.store.update_obligation(ob)
                fulfilled.append(ob)
                _log.info(
                    f"[AutoFulfill] Obligation {ob.obligation_id[:8]} ({ob.obligation_type}) "
                    f"fulfilled by event {ev.event_type} via pattern match"
                )

        return fulfilled

    # ── 私有：trigger (ObligationTrigger framework) ──────────────────────────

    def _match_and_create_trigger_obligations(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        P2-2: Automatic obligation trigger activation.

        When a tool_call event is ingested:
          1. Extract tool_name, tool_input, decision from payload
          2. Match against registered ObligationTriggers
          3. Create obligations for each matched trigger (with deduplication)

        Only fires for ALLOW decisions (denied tools don't create obligations).
        """
        if self.trigger_registry is None:
            return []

        # Extract tool call information from event payload
        payload = ev.payload or {}
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input", {})
        decision = payload.get("decision", "ALLOW")

        # Only fire triggers for ALLOW decisions
        # (DENY triggers are special and handled by hook layer)
        if decision != "ALLOW":
            return []

        if not tool_name:
            return []

        # Match triggers
        try:
            from ystar.governance.obligation_triggers import match_triggers
            triggers = match_triggers(
                registry=self.trigger_registry,
                tool_name=tool_name,
                tool_input=tool_input,
                agent_id=ev.actor_id,
                check_result=None,  # We already filtered by ALLOW above
            )
        except ImportError:
            # Optional import — trigger matching module not available
            return []

        # Create obligations for each matched trigger
        new_obs = []
        for trigger in triggers:
            # GracefulSkip: validate obligation_type is registered
            if not self._is_obligation_type_registered(trigger.obligation_type):
                self._write_trigger_skip_to_cieu(
                    trigger_id=trigger.trigger_id,
                    obligation_type=trigger.obligation_type,
                    reason="obligation_type_not_registered",
                    tool_name=tool_name,
                    actor_id=ev.actor_id,
                )
                _log.warning(
                    f"GracefulSkip: trigger={trigger.trigger_id} references unregistered "
                    f"obligation_type={trigger.obligation_type}, skipping"
                )
                continue  # Skip this trigger, continue with others

            # Determine target actor
            target_actor = trigger.get_target_actor(ev.actor_id)

            # Deduplication: check if same obligation type already pending
            if trigger.deduplicate:
                if self.store.has_pending_obligation(
                    entity_id=ev.entity_id,
                    obligation_type=trigger.obligation_type,
                    actor_id=target_actor,
                ):
                    continue  # Skip duplicate

            # Calculate deadline
            due_at = ev.ts + trigger.deadline_seconds

            # Map severity string to Severity enum
            severity = Severity.HIGH if trigger.severity == "HARD" else Severity.MEDIUM

            # Build escalation policy from trigger
            escalation_policy = EscalationPolicy(
                escalate_after_secs=trigger.deadline_seconds * 2 if trigger.escalate_to_hard else None,
                escalate_to=trigger.escalate_to_actor,
                actions=[EscalationAction.ESCALATE] if trigger.escalate_to_hard else [],
                deny_closure_on_open=trigger.deny_closure_on_open,
            )

            # Create obligation record
            ob = ObligationRecord(
                entity_id=ev.entity_id,
                actor_id=target_actor,
                obligation_type=trigger.obligation_type,
                trigger_event_id=ev.event_id,
                required_event_types=[trigger.fulfillment_event],
                due_at=due_at,
                grace_period_secs=trigger.grace_period_secs,
                hard_overdue_secs=trigger.hard_overdue_secs,
                status=ObligationStatus.PENDING,
                violation_code=f"trigger_{trigger.trigger_id}_violation",
                severity=severity,
                escalation_policy=escalation_policy,
                notes=f"auto-triggered by tool_call:{tool_name} (trigger_id={trigger.trigger_id})",
            )

            # Save to store
            self.store.add_obligation(ob)
            new_obs.append(ob)

        return new_obs

    # ── 私有：trigger (rule-based) ────────────────────────────────────────────

    def _trigger_obligations(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        检查事件是否触发任何 OmissionRule，并创建对应的 ObligationRecord。
        v0.42.0: 新增 tool_trigger 事件处理（ObligationTrigger 框架）。
        """
        # ── NEW: Handle tool_trigger events from ObligationTrigger framework ──
        if ev.event_type.startswith("tool_trigger:"):
            return self._create_triggered_obligation(ev)

        # ── Original rule-based obligation creation ──────────────────────────
        entity = self.store.get_entity(ev.entity_id)
        if entity is None:
            return []

        new_obs = []
        matching_rules = self.registry.rules_for_trigger(ev.event_type)

        for rule in matching_rules:
            # entity type 过滤
            if not rule.matches_entity_type(entity.entity_type):
                continue

            # 选择责任 actor
            actor_id = rule.actor_selector(entity, ev)
            if not actor_id:
                continue

            # GracefulSkip: validate obligation_type is registered
            if not self._is_obligation_type_registered(rule.obligation_type):
                self._write_trigger_skip_to_cieu(
                    trigger_id=rule.rule_id,
                    obligation_type=rule.obligation_type,
                    reason="obligation_type_not_registered",
                    tool_name=ev.event_type,
                    actor_id=actor_id,
                )
                _log.warning(
                    f"GracefulSkip: rule={rule.rule_id} references unregistered "
                    f"obligation_type={rule.obligation_type}, skipping"
                )
                continue  # Skip this rule, continue with others

            # 幂等：已有同类 pending obligation 则跳过
            if rule.deduplicate and self.store.has_pending_obligation(
                entity_id=ev.entity_id,
                obligation_type=rule.obligation_type,
                actor_id=actor_id,
            ):
                continue

            due_at = rule.compute_due_at(ev.ts)
            ob = ObligationRecord(
                entity_id            = ev.entity_id,
                actor_id             = actor_id,
                obligation_type      = rule.obligation_type,
                trigger_event_id     = ev.event_id,
                required_event_types = rule.required_event_types,
                due_at               = due_at,
                grace_period_secs    = rule.grace_period_secs,
                hard_overdue_secs    = rule.hard_overdue_secs,
                status               = ObligationStatus.PENDING,
                violation_code       = rule.violation_code,
                severity             = rule.severity,
                escalation_policy    = rule.escalation_policy,
                notes                = f"triggered by rule:{rule.rule_id}",
            )
            self.store.add_obligation(ob)
            new_obs.append(ob)

        return new_obs

    def _create_triggered_obligation(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        Create ObligationRecord from a tool_trigger event.
        Called when ObligationTrigger framework generates a tool_trigger:* event.

        Event payload contains:
          - trigger_id:     ID of the trigger that fired
          - obligation_type: type of obligation to create
          - deadline_secs:  deadline in seconds
          - fulfillment:    fulfillment event type
          - tool_name:      tool that triggered this
          - tool_input:     tool input parameters
          - triggered_by:   agent who triggered it
        """
        payload = ev.payload or {}
        trigger_id = payload.get("trigger_id", "unknown")
        obligation_type = payload.get("obligation_type", "unknown")
        deadline_secs = payload.get("deadline_secs", 3600)
        fulfillment = payload.get("fulfillment", "file_write")

        # GracefulSkip: validate obligation_type is registered
        if not self._is_obligation_type_registered(obligation_type):
            self._write_trigger_skip_to_cieu(
                trigger_id=trigger_id,
                obligation_type=obligation_type,
                reason="obligation_type_not_registered",
                tool_name=payload.get("tool_name", "unknown"),
                actor_id=ev.actor_id,
            )
            _log.warning(
                f"GracefulSkip: trigger={trigger_id} references unregistered "
                f"obligation_type={obligation_type}, skipping"
            )
            return []  # Skip this trigger

        # Calculate due_at from event timestamp
        due_at = ev.ts + deadline_secs

        # Get trigger details from registry to configure escalation
        from ystar.governance.obligation_triggers import get_trigger_registry
        registry = get_trigger_registry()
        trigger = registry.get(trigger_id) if registry else None

        # Configure escalation policy from trigger
        from ystar.governance.omission_models import EscalationPolicy, EscalationAction

        if trigger:
            escalation_policy = EscalationPolicy(
                escalate_after_secs=deadline_secs * 2 if trigger.escalate_to_hard else None,
                escalate_to=trigger.escalate_to_actor,
                actions=[EscalationAction.ESCALATE] if trigger.escalate_to_hard else [],
                deny_closure_on_open=trigger.deny_closure_on_open,
            )
            grace_period_secs = trigger.grace_period_secs
            hard_overdue_secs = trigger.hard_overdue_secs
            severity = Severity.HIGH if trigger.severity == "HARD" else Severity.MEDIUM
        else:
            escalation_policy = EscalationPolicy()
            grace_period_secs = 0.0
            hard_overdue_secs = deadline_secs
            severity = Severity.MEDIUM

        # Create obligation record
        ob = ObligationRecord(
            entity_id            = ev.entity_id,
            actor_id             = ev.actor_id,
            obligation_type      = obligation_type,
            trigger_event_id     = ev.event_id,
            required_event_types = [fulfillment],
            due_at               = due_at,
            grace_period_secs    = grace_period_secs,
            hard_overdue_secs    = hard_overdue_secs,
            status               = ObligationStatus.PENDING,
            violation_code       = f"trigger_{trigger_id}_violation",
            severity             = severity,
            escalation_policy    = escalation_policy,
            notes                = f"triggered by tool_trigger:{trigger_id}",
        )

        self.store.add_obligation(ob)
        return [ob]

    # ── 私有：violation 创建 ──────────────────────────────────────────────────

    def _create_violation(
        self,
        ob: ObligationRecord,
        now: float,
        overdue_secs: float,
    ) -> OmissionViolation:
        return OmissionViolation(
            entity_id     = ob.entity_id,
            obligation_id = ob.obligation_id,
            actor_id      = ob.actor_id,
            omission_type = ob.obligation_type,
            detected_at   = now,
            overdue_secs  = overdue_secs,
            severity      = ob.severity,
            details       = {
                "required_event_types": ob.required_event_types,
                "due_at":              ob.due_at,
                "effective_due_at":    ob.effective_due_at,
                "violation_code":      ob.violation_code,
                "obligation_id":       ob.obligation_id,
                "trigger_event_id":    ob.trigger_event_id,
            },
        )

    # ── 私有：activity gating ─────────────────────────────────────────────────

    def _is_entity_active(self, entity_id: str, now: float, window_secs: float = 600) -> bool:
        """
        Check if entity had recent activity (event within window_secs).
        Used to gate omission violations — don't fire violations for dormant entities.

        Fix for Circuit Breaker noise root cause (480/480/480/480 timer-fired violations).
        Violations should only fire when agent is active but failed to produce expected artifact.

        Args:
            entity_id: Entity to check
            now: Current timestamp
            window_secs: Activity window (default 10 min)

        Returns:
            True if entity had events in last window_secs, False otherwise
        """
        entity = self.store.get_entity(entity_id)
        if entity is None:
            return False

        # Check last_event_at timestamp
        if entity.last_event_at is None:
            return False

        return (now - entity.last_event_at) <= window_secs

    # ── 私有：reminder ─────────────────────────────────────────────────────────
    # N8 CONFIRMED: All escalation/reminder timing comes from EscalationPolicy
    # object fields (escalate_after_secs, reminder_after_secs), not from inline
    # constants. EscalationPolicy is set per-obligation at creation time via
    # OmissionRule or ObligationTrigger configuration.

    def _should_remind(self, ob: ObligationRecord, now: float) -> bool:
        if ob.reminder_sent_at is not None:
            return False  # 已发过 reminder，不重复
        reminder_secs = ob.escalation_policy.reminder_after_secs
        if reminder_secs is None:
            return False
        if ob.due_at is None:
            return False
        remind_at = ob.due_at - reminder_secs if reminder_secs > 0 else ob.due_at
        # 当剩余时间 <= reminder_secs 时发 reminder
        return now >= (ob.due_at - reminder_secs)

    # ── 私有：escalation ───────────────────────────────────────────────────────

    def _matches_fulfiller_pattern(self, ob: ObligationRecord, ev: GovernanceEvent) -> bool:
        """
        v0.50: Check if event matches the fulfiller pattern for this obligation type.

        Auto-fulfillment logic (AMENDMENT-012 integration):
          1. Lookup fulfiller descriptor for obligation_type
          2. Check if event_type matches fulfillment_event_pattern
          3. Substitute template variables ($OBLIGATION_ACTOR_ID → ob.actor_id)
          4. Return True if pattern matches

        Returns:
            True if event fulfills this obligation via pattern match, False otherwise.
        """
        try:
            # Import fulfiller registry (lazy load to avoid circular dependency)
            import sys
            from pathlib import Path
            ystar_root = Path(__file__).parent.parent.parent
            sys.path.insert(0, str(ystar_root / "scripts"))
            from migrate_9_obligation_fulfillers import get_fulfiller_for_type
        except ImportError:
            # Fulfiller migration not installed yet
            return False

        fulfiller = get_fulfiller_for_type(ob.obligation_type)
        if fulfiller is None or fulfiller.fulfillment_event_pattern is None:
            return False

        pattern = fulfiller.fulfillment_event_pattern

        # Match event_type (can be single string or list of strings)
        pattern_event_type = pattern.get("event_type")
        if pattern_event_type:
            if isinstance(pattern_event_type, list):
                if ev.event_type not in pattern_event_type:
                    return False
            elif ev.event_type != pattern_event_type:
                return False

        # Match actor_id with template substitution
        pattern_actor_id = pattern.get("actor_id")
        if pattern_actor_id:
            # Substitute template variable
            expected_actor_id = pattern_actor_id.replace("$OBLIGATION_ACTOR_ID", ob.actor_id)
            if ev.actor_id != expected_actor_id:
                return False

        # Additional pattern fields (future: payload matching, file path matching, etc.)
        # For MVP: only event_type + actor_id matching

        return True

    def _should_escalate(self, ob: ObligationRecord, now: float) -> bool:
        if ob.escalated:
            return False
        esc_secs = ob.escalation_policy.escalate_after_secs
        if esc_secs is None:
            return False
        if EscalationAction.ESCALATE not in ob.escalation_policy.actions:
            return False
        if ob.effective_due_at is None:
            return False
        return now >= (ob.effective_due_at + esc_secs)

    def _escalate(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
        now: float,
    ) -> OmissionViolation:
        ob.escalated    = True
        ob.escalated_at = now
        ob.status       = ObligationStatus.ESCALATED
        self.store.update_obligation(ob)

        v.escalated   = True
        v.escalated_to = ob.escalation_policy.escalate_to or "supervisor"
        return v

    # ── 私有：entity 状态更新 ─────────────────────────────────────────────────

    def _update_entity_on_violation(self, ob: ObligationRecord) -> None:
        entity = self.store.get_entity(ob.entity_id)
        if entity is None:
            return
        # 如果 obligation 是 HIGH/CRITICAL 且 entity 还在 ACTIVE，升级到 EXPIRED
        if (ob.severity in (Severity.HIGH, Severity.CRITICAL)
                and entity.status == EntityStatus.ACTIVE):
            entity.status = EntityStatus.EXPIRED
            entity.touch()
            self.store.upsert_entity(entity)

    # ── 私有：CIEU 写入 ────────────────────────────────────────────────────────

    def _write_to_cieu(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
    ) -> None:
        try:
            cieu_record = {
                "event_id":    str(uuid.uuid4()),
                "seq_global":  int(self._now() * 1_000_000),
                "created_at":  self._now(),
                "session_id":  ob.entity_id,
                "agent_id":    ob.actor_id,
                "event_type":  f"omission_violation:{ob.obligation_type}",
                "decision":    "escalate",
                "passed":      False,
                "violations":  [{
                    "dimension":  "omission_governance",
                    "field":      "required_event",
                    "message":    (
                        f"{ob.obligation_type}: actor '{ob.actor_id}' "
                        f"failed to produce {ob.required_event_types} "
                        f"for entity '{ob.entity_id}' "
                        f"(overdue {v.overdue_secs:.1f}s)"
                    ),
                    "actual":     "no_required_event",
                    "constraint": f"due_at={ob.due_at}",
                    "severity":   0.8 if ob.severity == Severity.HIGH else 0.5,
                }],
                "drift_detected": True,
                "drift_details":  f"omission_type={ob.obligation_type}",
                "drift_category": "omission_failure",
                "task_description": (
                    f"Omission: {ob.obligation_type} | "
                    f"entity={ob.entity_id} | actor={ob.actor_id}"
                ),
                "evidence_grade": "governance",  # [P2-3] omission 是治理级证据
            }
            ok = self.cieu_store.write_dict(cieu_record)
            if ok:
                v.cieu_ref = cieu_record["event_id"]
        except Exception as e:
            # CIEU 写入失败不阻断主流程
            _log.error("Failed to write violation to CIEU (violation_id=%s): %s", v.violation_id, e)

    def _is_obligation_type_registered(self, obligation_type: str) -> bool:
        """
        Check if an obligation_type is registered in the system.

        Validates against:
          1. Built-in OmissionType enum values

        GracefulSkip: Returns False for unregistered types, triggering a warning
        rather than a violation cascade.

        Note: We intentionally do NOT check rule registry here, as that would
        create circular validation. A rule that defines a new obligation type
        would always pass validation, defeating the purpose of GracefulSkip.
        Only OmissionType enum values are considered authoritative.
        """
        # Check against OmissionType enum (authoritative source)
        try:
            known_types = {ot.value for ot in OmissionType}
            if obligation_type in known_types:
                return True
        except Exception:
            pass

        # Unregistered type — return False to trigger GracefulSkip
        return False

    def _write_trigger_skip_to_cieu(
        self,
        trigger_id: str,
        obligation_type: str,
        reason: str,
        tool_name: str,
        actor_id: str,
    ) -> None:
        """
        Write GracefulSkip event to CIEU when a trigger is skipped.

        This is NOT a violation - just an info-level audit record.
        """
        try:
            cieu_record = {
                "event_id":    str(uuid.uuid4()),
                "seq_global":  int(self._now() * 1_000_000),
                "created_at":  self._now(),
                "session_id":  "system",
                "agent_id":    actor_id,
                "event_type":  "obligation_trigger_skipped",
                "decision":    "skip",
                "passed":      True,  # Not a failure, just a skip
                "violations":  [],
                "drift_detected": False,
                "task_description": (
                    f"GracefulSkip: trigger={trigger_id} | "
                    f"obligation_type={obligation_type} | "
                    f"reason={reason} | tool={tool_name}"
                ),
                "evidence_grade": "info",
                "metadata": {
                    "trigger_id": trigger_id,
                    "obligation_type": obligation_type,
                    "reason": reason,
                    "tool_name": tool_name,
                },
            }
            self.cieu_store.write_dict(cieu_record)
        except Exception as e:
            # CIEU write failure doesn't block main flow
            _log.debug("Failed to write trigger skip to CIEU (trigger_id=%s): %s", trigger_id, e)

    def _write_restoration_to_cieu(
        self,
        ob: ObligationRecord,
        restoration_event: GovernanceEvent,
    ) -> None:
        """写入 OBLIGATION_RESTORED 到 CIEU（证据链）。"""
        try:
            cieu_record = {
                "event_id":    restoration_event.event_id,
                "seq_global":  int(self._now() * 1_000_000),
                "created_at":  self._now(),
                "session_id":  ob.entity_id,
                "agent_id":    ob.actor_id,
                "event_type":  "obligation_restored",
                "decision":    "allow",
                "passed":      True,
                "violations":  [],
                "drift_detected": False,
                "drift_details":  (
                    f"obligation_restored: {ob.obligation_type} | "
                    f"obligation_id={ob.obligation_id} | "
                    f"restored_at={ob.restored_at}"
                ),
                "drift_category": "restoration_success",
                "task_description": (
                    f"Restoration: {ob.obligation_type} | "
                    f"entity={ob.entity_id} | actor={ob.actor_id}"
                ),
                "evidence_grade": "governance",  # [P2-3] restoration 是治理级证据
            }
            self.cieu_store.write_dict(cieu_record)
        except Exception as e:
            # CIEU 写入失败不阻断主流程
            _log.error("Failed to write restoration to CIEU (ob_id=%s): %s", ob.ob_id, e)

    # ── 主入口 3：Restoration（补救过期义务）──────────────────────────────────

    def restore_obligation(
        self,
        obligation_id: str,
        actor_id: str,
        event_id: Optional[str] = None,
    ) -> RestorationResult:
        """
        恢复（补救）一个过期的 obligation。

        条件：
          1. obligation 必须存在且处于 expired/violated 状态
             (EXPIRED, SOFT_OVERDUE, HARD_OVERDUE, ESCALATED)
          2. 当前时间必须在 restoration grace period 内
             (restoration_deadline = due_at + original_deadline_duration * multiplier)

        成功后：
          - obligation 状态转为 RESTORED
          - 写入 OBLIGATION_RESTORED 事件到 store
          - 返回 RestorationResult(success=True)

        失败返回：
          - not_found: obligation 不存在
          - wrong_actor: actor_id 不匹配
          - not_restorable: obligation 不在可恢复状态
          - beyond_grace_period: 超出恢复宽限期
        """
        now = self._now()

        # 1. 查找 obligation
        ob = self.store.get_obligation(obligation_id)
        if ob is None:
            return RestorationResult(
                success=False,
                obligation_id=obligation_id,
                actor_id=actor_id,
                failure_reason="not_found",
            )

        # 2. 检查 actor 匹配
        if ob.actor_id != actor_id:
            return RestorationResult(
                success=False,
                obligation_id=obligation_id,
                actor_id=actor_id,
                failure_reason="wrong_actor",
            )

        # 3. 检查状态（必须是可恢复状态）
        restorable_states = (
            ObligationStatus.EXPIRED,
            ObligationStatus.SOFT_OVERDUE,
            ObligationStatus.HARD_OVERDUE,
            ObligationStatus.ESCALATED,
        )
        if ob.status not in restorable_states:
            return RestorationResult(
                success=False,
                obligation_id=obligation_id,
                actor_id=actor_id,
                failure_reason="not_restorable",
            )

        # 4. 检查是否在 restoration grace period 内
        if not ob.can_restore(now):
            return RestorationResult(
                success=False,
                obligation_id=obligation_id,
                actor_id=actor_id,
                restored_at=now,
                failure_reason="beyond_grace_period",
            )

        # 5. 创建 OBLIGATION_RESTORED 事件 ID
        restoration_event_id = event_id or str(uuid.uuid4())

        # 6. 执行恢复
        ob.status = ObligationStatus.RESTORED
        ob.restored_at = now
        ob.restored_by_event_id = restoration_event_id
        ob.updated_at = now
        self.store.update_obligation(ob)

        # 7. 写入 OBLIGATION_RESTORED 事件
        restoration_event = GovernanceEvent(
            event_id=restoration_event_id,
            event_type=GEventType.OBLIGATION_RESTORED,
            entity_id=ob.entity_id,
            actor_id=actor_id,
            ts=now,
            payload={
                "obligation_id": obligation_id,
                "obligation_type": ob.obligation_type,
                "was_status": "expired",  # 记录原状态（已经更新为 RESTORED，这里记录之前的）
                "restored_at": now,
            },
            source="omission_engine",
        )
        self.store.add_event(restoration_event)

        # 8. 写入 CIEU（可选）
        self._write_restoration_to_cieu(ob, restoration_event)

        return RestorationResult(
            success=True,
            obligation_id=obligation_id,
            actor_id=actor_id,
            restored_at=now,
            governance_event_id=restoration_event_id,
        )

    # ── v0.48: Graceful Cancellation ──────────────────────────────────────────

    def cancel_obligation(
        self,
        obligation_id: str,
        reason: str,
        now: Optional[float] = None,
    ) -> Optional[ObligationRecord]:
        """
        Cancel a pending obligation without creating violation.

        Writes CIEU info event. Common reasons:
        - "session_ended": session boundary auto-cancel
        - "user_requested": manual cancellation
        - "superseded": replaced by newer obligation
        - "no_longer_applicable": context changed

        Args:
            obligation_id: ID of obligation to cancel
            reason: Human-readable cancellation reason
            now: Current timestamp (default: time.time())

        Returns:
            Updated ObligationRecord with status=CANCELLED, or None if not found
        """
        now = now or self._now()

        # Load obligation
        obligation = self.store.get_obligation(obligation_id)
        if not obligation:
            _log.warning(f"cancel_obligation: {obligation_id} not found")
            return None

        # Only cancel if PENDING or SOFT_OVERDUE
        if obligation.status not in (ObligationStatus.PENDING, ObligationStatus.SOFT_OVERDUE):
            _log.warning(
                f"cancel_obligation: {obligation_id} has status {obligation.status}, "
                f"cannot cancel (only PENDING/SOFT_OVERDUE can be cancelled)"
            )
            return None

        # Update status
        obligation.status = ObligationStatus.CANCELLED
        obligation.cancelled_at = now
        obligation.cancellation_reason = reason
        obligation.updated_at = now

        # Save to store
        self.store.update_obligation(obligation)

        # Write CIEU info event
        self.cieu_store.write({
            "event_type": "obligation_cancelled",
            "decision": "info",
            "obligation_id": obligation_id,
            "obligation_type": obligation.obligation_type,
            "entity_id": obligation.entity_id,
            "actor_id": obligation.actor_id,
            "session_id": obligation.session_id,
            "reason": reason,
            "was_overdue": obligation.status == ObligationStatus.SOFT_OVERDUE,
            "timestamp": now,
        })

        _log.info(
            f"Cancelled obligation {obligation_id} "
            f"(type={obligation.obligation_type}, reason={reason})"
        )

        return obligation

    def cancel_session_obligations(
        self,
        old_session_id: str,
        new_session_id: str,
        now: Optional[float] = None,
    ) -> int:
        """
        Auto-cancel all PENDING obligations from previous session.

        Called at session boundary. Prevents obligation accumulation
        across sessions without losing audit trail.

        Args:
            old_session_id: Previous session ID
            new_session_id: New session ID (for logging)
            now: Current timestamp

        Returns:
            Number of obligations cancelled
        """
        now = now or self._now()

        # Find all PENDING/SOFT_OVERDUE obligations from old session
        all_obligations = self.store.list_obligations()
        old_session_obligations = [
            o for o in all_obligations
            if o.session_id == old_session_id
            and o.status in (ObligationStatus.PENDING, ObligationStatus.SOFT_OVERDUE)
        ]

        # Cancel each
        cancelled_count = 0
        for obligation in old_session_obligations:
            result = self.cancel_obligation(
                obligation.obligation_id,
                reason=f"session_ended (old={old_session_id}, new={new_session_id})",
                now=now,
            )
            if result:
                cancelled_count += 1

        _log.info(
            f"Session boundary: cancelled {cancelled_count} obligations "
            f"from session {old_session_id}"
        )

        # Write CIEU summary event
        self.cieu_store.write({
            "event_type": "session_boundary_cleanup",
            "decision": "info",
            "old_session_id": old_session_id,
            "new_session_id": new_session_id,
            "cancelled_count": cancelled_count,
            "timestamp": now,
        })

        return cancelled_count

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def obligation_status_report(self, entity_id: str) -> dict:
        """返回某 entity 的义务状态报告。"""
        all_obs = self.store.list_obligations(entity_id=entity_id)
        by_status: Dict[str, list] = {}
        for ob in all_obs:
            by_status.setdefault(ob.status.value, []).append(ob.to_dict())
        violations = [
            v.to_dict()
            for v in self.store.list_violations(entity_id=entity_id)
        ]
        return {
            "entity_id":   entity_id,
            "obligations": by_status,
            "violations":  violations,
            "can_close":   self.can_close(entity_id),
        }
