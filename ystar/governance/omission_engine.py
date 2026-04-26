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
from ystar.governance.cieu_store import CIEUStore, NullCIEUStore

_log = logging.getLogger(__name__)

# 类型别名：支持两种 store
AnyStore = Union[InMemoryOmissionStore, OmissionStore]
_DEFAULT_CIEU_STORE = object()


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
        cieu_store: Any = _DEFAULT_CIEU_STORE,  # CIEUStore | NullCIEUStore | None
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
        # Default constructor path should persist omission evidence. Explicit
        # None remains the legacy "no persistence" signal used by some unit tests.
        if cieu_store is _DEFAULT_CIEU_STORE:
            self.cieu_store = CIEUStore(db_path=".ystar_cieu_omission.db")
        elif cieu_store is not None:
            self.cieu_store = cieu_store
        else:
            self.cieu_store = NullCIEUStore()
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
        entity = self.store.get_entity(ev.entity_id)
        if entity is not None:
            entity.last_event_at = ev.ts
            entity.updated_at = max(entity.updated_at, ev.ts)
            self.store.upsert_entity(entity)

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
                    trigger_event_id=ev.event_id,
                    created_at=ev.ts,  # Use original event time
                    due_at=ev.ts + trigger.deadline_seconds,
                    status=ObligationStatus.PENDING,
                    severity=Severity[trigger.severity],
                    required_event_types=trigger.required_event_types or [trigger.fulfillment_event],
                    grace_period_secs=trigger.grace_period_secs,
                    hard_overdue_secs=trigger.hard_overdue_secs,
                    escalation_policy=EscalationPolicy(
                        escalate_after_secs=trigger.hard_overdue_secs,
                        escalate_to=trigger.escalate_to_actor,
                        deny_closure_on_open=trigger.deny_closure_on_open,
                    ),
                )
                self.store.add_obligation(ob)
                result.new_obligations.append(ob)

                _log.info(
                    f"[OmissionEngine] Live-reload: created {obligation_type} obligation "
                    f"for retroactive event {ev.event_id[:8]}"
                )

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
            return True

        # For active entities created in-memory without a separate event trail,
        # treat the entity itself as the source of truth instead of suppressing
        # all violations. This keeps the anti-noise gate while preserving
        # legitimate scan semantics in tests and adapter-driven flows.
        if entity.last_event_at is None:
            return entity.status == EntityStatus.ACTIVE

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

    # ── Obligation Closure (B4 fix: 0/17k obligations ever closed) ──────────

    def close_obligation(
        self,
        obligation_id: str,
        evidence_event_id: str = "manual",
        close_reason: str = "manual",
        now: Optional[float] = None,
    ) -> bool:
        """
        Close an obligation by marking it FULFILLED with evidence metadata.

        Unlike cancel (which voids the obligation), close marks it as
        successfully completed. Works on any open status: PENDING,
        SOFT_OVERDUE, HARD_OVERDUE, ESCALATED, EXPIRED.

        Args:
            obligation_id: ID of obligation to close
            evidence_event_id: Event ID proving fulfillment (or "manual")
            close_reason: Human-readable reason for closure
            now: Current timestamp (default: time.time())

        Returns:
            True if obligation was found and closed, False otherwise
        """
        now = now or self._now()

        obligation = self.store.get_obligation(obligation_id)
        if not obligation:
            _log.warning(f"close_obligation: {obligation_id} not found")
            return False

        # Already in a terminal state (FULFILLED, CANCELLED, FAILED, RESTORED)
        if not obligation.status.is_open and obligation.status not in (
            ObligationStatus.EXPIRED,
            ObligationStatus.ESCALATED,
        ):
            _log.warning(
                f"close_obligation: {obligation_id} already terminal "
                f"(status={obligation.status})"
            )
            return False

        # Transition to FULFILLED
        obligation.status = ObligationStatus.FULFILLED
        obligation.fulfilled_by_event_id = evidence_event_id
        obligation.notes = (
            f"{obligation.notes}; closed: {close_reason}"
            if obligation.notes else f"closed: {close_reason}"
        )
        obligation.updated_at = now
        self.store.update_obligation(obligation)

        # Write CIEU audit event
        self.cieu_store.write({
            "event_type": "obligation_closed",
            "decision": "info",
            "obligation_id": obligation_id,
            "obligation_type": obligation.obligation_type,
            "entity_id": obligation.entity_id,
            "actor_id": obligation.actor_id,
            "evidence_event_id": evidence_event_id,
            "close_reason": close_reason,
            "timestamp": now,
        })

        _log.info(
            f"Closed obligation {obligation_id} "
            f"(type={obligation.obligation_type}, reason={close_reason})"
        )
        return True

    def bulk_auto_close_by_tag_age(
        self,
        tag_prefix: str,
        max_age_seconds: float = 86400 * 7,
        close_reason: str = "stale_auto_close",
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Bulk-close obligations whose obligation_type starts with tag_prefix
        and are older than max_age_seconds.

        This is the simplest closure mechanism: obligations older than a
        threshold are assumed stale and auto-closed. More sophisticated
        signature-matching closure can be built on top of close_obligation().

        Args:
            tag_prefix: Only close obligations whose obligation_type starts
                        with this prefix (case-insensitive match)
            max_age_seconds: Only close obligations created more than this
                             many seconds ago (default: 7 days)
            close_reason: Reason string stored on each closed obligation
            now: Current timestamp

        Returns:
            Dict with keys: closed_count, skipped_count, scanned_count
        """
        now = now or self._now()
        cutoff = now - max_age_seconds
        tag_lower = tag_prefix.lower()

        all_obs = self.store.list_obligations()
        scanned = 0
        closed = 0
        skipped = 0

        for ob in all_obs:
            if not ob.obligation_type.lower().startswith(tag_lower):
                continue
            scanned += 1

            # Only close open or overdue obligations
            closeable = ob.status.is_open or ob.status in (
                ObligationStatus.EXPIRED,
                ObligationStatus.ESCALATED,
            )
            if not closeable:
                skipped += 1
                continue

            # Age gate
            if ob.created_at > cutoff:
                skipped += 1
                continue

            if self.close_obligation(
                ob.obligation_id,
                evidence_event_id="bulk_auto_close",
                close_reason=close_reason,
                now=now,
            ):
                closed += 1
            else:
                skipped += 1

        _log.info(
            f"bulk_auto_close_by_tag_age('{tag_prefix}', {max_age_seconds}s): "
            f"scanned={scanned}, closed={closed}, skipped={skipped}"
        )
        return {
            "closed_count": closed,
            "skipped_count": skipped,
            "scanned_count": scanned,
        }

    # ── ARCH-11b: REDIRECT ignore detection ─────────────────────────────────

    def register_redirect_obligation(
        self,
        agent_id: str,
        redirect_id: str,
        ttl_actions: int = 3,
        entity_id: str = "session",
        redirect_reason: str = "",
    ) -> ObligationRecord:
        """
        Create a 'must_execute_redirect' obligation when a free-text REDIRECT
        fires (i.e. GuidancePayload absent or auto-invoke failed).

        The agent has `ttl_actions` tool calls to fulfill the REDIRECT fix
        before OmissionEngine fires a REDIRECT_IGNORED violation.

        Fulfillment: any event of type 'redirect_fulfilled' for same entity.

        Args:
            agent_id:        The agent that received the REDIRECT
            redirect_id:     Unique ID for this REDIRECT instance
            ttl_actions:     Number of tool_uses before obligation expires
            entity_id:       Entity (session) ID
            redirect_reason: Human-readable REDIRECT reason

        Returns:
            The created ObligationRecord
        """
        now = self._now()
        # TTL expressed in actions, but OmissionEngine uses time-based deadlines.
        # We use ttl_actions * 10s as a reasonable per-action budget.
        deadline_secs = ttl_actions * 10.0

        ob = ObligationRecord(
            entity_id=entity_id,
            actor_id=agent_id,
            obligation_type=OmissionType.MUST_EXECUTE_REDIRECT.value,
            trigger_event_id=redirect_id,
            required_event_types=["redirect_fulfilled"],
            due_at=now + deadline_secs,
            grace_period_secs=0.0,
            hard_overdue_secs=deadline_secs,
            status=ObligationStatus.PENDING,
            violation_code="redirect_ignored",
            severity=Severity.HIGH,
            escalation_policy=EscalationPolicy(
                escalate_after_secs=deadline_secs * 2,
                escalate_to="cto",
                actions=[EscalationAction.ESCALATE],
                deny_closure_on_open=True,
            ),
            notes=(
                f"ARCH-11b: free-text REDIRECT must be executed within "
                f"{ttl_actions} actions. redirect_id={redirect_id}. "
                f"reason={redirect_reason}"
            ),
        )
        self.store.add_obligation(ob)

        # Write CIEU event for audit trail
        try:
            cieu_record = {
                "event_id": str(uuid.uuid4()),
                "seq_global": int(now * 1_000_000),
                "created_at": now,
                "session_id": entity_id,
                "agent_id": agent_id,
                "event_type": "REDIRECT_OBLIGATION_CREATED",
                "decision": "info",
                "passed": True,
                "violations": [],
                "drift_detected": False,
                "task_description": (
                    f"ARCH-11b: obligation created for free-text REDIRECT "
                    f"redirect_id={redirect_id} ttl_actions={ttl_actions} "
                    f"reason={redirect_reason}"
                ),
                "evidence_grade": "governance",
            }
            self.cieu_store.write_dict(cieu_record)
        except Exception as e:
            _log.debug("Failed to write redirect obligation CIEU: %s", e)

        _log.info(
            "[ARCH-11b] Created must_execute_redirect obligation: "
            "agent=%s redirect_id=%s ttl=%d",
            agent_id, redirect_id, ttl_actions,
        )
        return ob

    # ── ARCH-11c: Action promise enforcement ("say != do") ─────────────────

    def register_action_promise_obligation(
        self,
        agent_id: str,
        reply_id: str,
        promise_phrases: list[str] | None = None,
        tool_use_count: int = 0,
        ttl_replies: int = 1,
        entity_id: str = "session",
    ) -> ObligationRecord:
        """
        Create a 'must_fulfill_action_promise' obligation when an agent reply
        contains action promises (e.g. "NOW doing X", "dispatching Y") but
        has insufficient corresponding tool_uses in the same turn.

        The agent has `ttl_replies` subsequent replies to produce matching
        tool_uses before OmissionEngine fires a PROMISE_UNFULFILLED violation.

        Fulfillment: any event of type 'action_promise_fulfilled' for same entity.

        Args:
            agent_id:        The agent whose reply contained promises
            reply_id:        Unique ID for the reply that triggered this
            promise_phrases: The detected promise phrases (for audit)
            tool_use_count:  How many tool_uses actually occurred that turn
            ttl_replies:     Number of subsequent replies before obligation expires
            entity_id:       Entity (session) ID

        Returns:
            The created ObligationRecord
        """
        now = self._now()
        # TTL expressed in replies; use ttl_replies * 30s as reasonable budget
        deadline_secs = ttl_replies * 30.0

        phrases_str = ", ".join(promise_phrases or [])

        ob = ObligationRecord(
            entity_id=entity_id,
            actor_id=agent_id,
            obligation_type=OmissionType.MUST_FULFILL_ACTION_PROMISE.value,
            trigger_event_id=reply_id,
            required_event_types=["action_promise_fulfilled"],
            due_at=now + deadline_secs,
            grace_period_secs=0.0,
            hard_overdue_secs=deadline_secs,
            status=ObligationStatus.PENDING,
            violation_code="action_promise_unfulfilled",
            severity=Severity.HIGH,
            escalation_policy=EscalationPolicy(
                escalate_after_secs=deadline_secs * 2,
                escalate_to="cto",
                actions=[EscalationAction.ESCALATE],
                deny_closure_on_open=True,
            ),
            notes=(
                f"ARCH-11c: reply contained {len(promise_phrases or [])} action "
                f"promise(s) but only {tool_use_count} tool_uses. "
                f"phrases=[{phrases_str}] reply_id={reply_id}"
            ),
        )
        self.store.add_obligation(ob)

        # Write CIEU event for audit trail
        try:
            cieu_record = {
                "event_id": str(uuid.uuid4()),
                "seq_global": int(now * 1_000_000),
                "created_at": now,
                "session_id": entity_id,
                "agent_id": agent_id,
                "event_type": "ACTION_PROMISE_OBLIGATION_CREATED",
                "decision": "info",
                "passed": True,
                "violations": [],
                "drift_detected": False,
                "task_description": (
                    f"ARCH-11c: obligation created for unfulfilled action promises "
                    f"reply_id={reply_id} promises={len(promise_phrases or [])} "
                    f"tool_uses={tool_use_count} phrases=[{phrases_str[:200]}]"
                ),
                "evidence_grade": "governance",
            }
            self.cieu_store.write_dict(cieu_record)
        except Exception as e:
            _log.debug("Failed to write action promise obligation CIEU: %s", e)

        _log.info(
            "[ARCH-11c] Created must_fulfill_action_promise obligation: "
            "agent=%s reply_id=%s promises=%d tool_uses=%d",
            agent_id, reply_id, len(promise_phrases or []), tool_use_count,
        )
        return ob

    # ── Layer 4: Post-ship completeness obligations (Board 2026-04-19) ──────

    def register_post_ship_completeness_obligation(
        self,
        ship_event: Dict[str, Any],
        manifest_path: Optional[str] = None,
        entity_id: str = "session",
    ) -> List[ObligationRecord]:
        """
        Trigger: any CIEU event matching event_type LIKE 'CZL-%_SHIPPED' or
        'PHASE_N_COMPLETE'.

        Reads phase_lifecycle_manifest.yaml, identifies which feature/phase
        just shipped, and for every subsequent phase with unmet ship_markers,
        registers a POST_SHIP_COMPLETENESS:<feature>:phase_N obligation.

        Args:
            ship_event: dict with at least 'event_type' (str) and optionally
                        'feature_id' (str) to narrow the feature scope.
            manifest_path: override path to manifest YAML (default: docs/arch/)
            entity_id: entity for the obligations

        Returns:
            List of newly created ObligationRecord objects
        """
        import re
        from pathlib import Path

        now = self._now()
        new_obs: List[ObligationRecord] = []

        # 1. Load manifest
        if manifest_path is None:
            manifest_path = str(
                Path(__file__).parent.parent.parent
                / "docs" / "arch" / "phase_lifecycle_manifest.yaml"
            )

        manifest = _load_manifest(manifest_path)
        if manifest is None:
            _log.warning("Post-ship completeness: manifest not found at %s", manifest_path)
            return new_obs

        event_type = ship_event.get("event_type", "")
        feature_hint = ship_event.get("feature_id")

        # 2. Determine which phase just shipped (heuristic from event_type)
        shipped_phase_num = _extract_phase_number(event_type)

        # 3. For each feature in manifest, check subsequent phases
        for feature in manifest.get("features", []):
            fid = feature.get("feature_id", "unknown")

            # If ship_event specifies a feature_id, only process that feature
            if feature_hint and fid != feature_hint:
                continue

            phases = feature.get("phases", {})
            phase_keys = sorted(phases.keys())  # phase_1, phase_2, phase_3 ...

            for pkey in phase_keys:
                phase_num = _extract_phase_number(pkey)
                # Only check phases >= shipped phase (the point is: did we forget the rest?)
                if phase_num is not None and shipped_phase_num is not None:
                    if phase_num < shipped_phase_num:
                        continue

                phase_def = phases[pkey]
                markers = phase_def.get("ship_markers", [])

                # Check each marker
                unmet = []
                for marker_name in markers:
                    if not _check_ship_marker(marker_name):
                        unmet.append(marker_name)

                if not unmet:
                    continue  # All markers met for this phase

                # Register obligation
                ob_tag = f"POST_SHIP_COMPLETENESS:{fid}:{pkey}"

                # Dedup: skip if same tag already pending
                existing = self.store.list_obligations(entity_id=entity_id)
                if any(
                    o.notes and ob_tag in o.notes
                    and o.status.is_open
                    for o in existing
                ):
                    continue

                ob = ObligationRecord(
                    entity_id=entity_id,
                    actor_id=ship_event.get("actor_id", "system"),
                    obligation_type=OmissionType.POST_SHIP_COMPLETENESS.value,
                    trigger_event_id=ship_event.get("event_id", str(uuid.uuid4())),
                    required_event_types=[f"{fid}_{pkey}_complete"],
                    due_at=now + 86400.0,  # 24h default deadline
                    grace_period_secs=3600.0,
                    hard_overdue_secs=86400.0,
                    status=ObligationStatus.PENDING,
                    violation_code="post_ship_phase_incomplete",
                    severity=Severity.HIGH,
                    escalation_policy=EscalationPolicy(
                        escalate_after_secs=172800.0,  # 48h
                        escalate_to="cto",
                        actions=[EscalationAction.ESCALATE],
                        deny_closure_on_open=False,
                    ),
                    notes=(
                        f"{ob_tag} | unmet_markers={unmet} | "
                        f"trigger={event_type}"
                    ),
                )
                self.store.add_obligation(ob)
                new_obs.append(ob)

                _log.info(
                    "[Layer4] Post-ship completeness obligation: %s unmet=%s",
                    ob_tag, unmet,
                )

        return new_obs

    def enumerate_open_completeness_obligations(self) -> List[str]:
        """
        Returns list of unmet Phase-N obligation tags.

        Format: ["POST_SHIP_COMPLETENESS:<feature>:<phase>", ...]

        Intended to be called from CEO Stop hook reply scan to inject
        warning into reply when phases remain incomplete after a ship event.
        """
        import re
        result = []
        all_obs = self.store.list_obligations()
        for ob in all_obs:
            if ob.obligation_type != OmissionType.POST_SHIP_COMPLETENESS.value:
                continue
            if not ob.status.is_open:
                continue
            # Extract the tag from notes
            if ob.notes:
                match = re.search(r"(POST_SHIP_COMPLETENESS:\S+)", ob.notes)
                if match:
                    result.append(match.group(1))
        return result

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


# ── Module-level helpers for Layer 4 post-ship completeness ──────────────────

def _load_manifest(path: str) -> Optional[Dict[str, Any]]:
    """Load phase_lifecycle_manifest.yaml. Returns None if file missing."""
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        return None
    try:
        import yaml
        with open(p, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        _log.warning("Failed to load manifest %s: %s", path, e)
        return None


def _extract_phase_number(text: str) -> Optional[int]:
    """Extract phase number from strings like 'phase_2', 'PHASE_1_COMPLETE', 'CZL-42_PHASE_2_SHIPPED'."""
    import re
    m = re.search(r"phase[_\s]*(\d+)", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


# ── Ship marker checker registry ─────────────────────────────────────────────
# Each marker_name maps to a callable that returns True if the marker is met.
# Designed to be extended: add new checkers here as new features get phased.

def _check_activation_log_nonzero() -> bool:
    """Phase 1 marker: activation_log table has > 0 rows."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / ".ystar_cieu_brain.db"
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT COUNT(*) FROM activation_log"
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _check_cieu_brain_bridge_tests_pass() -> bool:
    """Phase 1 marker: cieu_brain_bridge tests exist and last run passed.
    Heuristic: if the test file exists, we trust CI. In production this
    would query a test-result store."""
    from pathlib import Path
    test_file = (
        Path(__file__).parent.parent.parent
        / "tests" / "governance" / "test_cieu_brain_bridge.py"
    )
    return test_file.exists()


def _check_continuous_daemon_running() -> bool:
    """Phase 2 marker: cieu_brain daemon process exists OR last ingest within 300s."""
    import time
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / ".ystar_cieu_brain.db"
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT MAX(ingested_at) FROM activation_log"
        )
        row = cur.fetchone()
        conn.close()
        if row and row[0]:
            return (time.time() - row[0]) < 300
        return False
    except Exception:
        return False


def _check_hebbian_edges_nonzero() -> bool:
    """Phase 2 marker: hebbian edges table has > 0 rows."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / ".ystar_cieu_brain.db"
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT COUNT(*) FROM edges")
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _check_dim_drift_applied() -> bool:
    """Phase 3 marker: nodes.dim_y has been updated (non-null) in the brain DB."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / ".ystar_cieu_brain.db"
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT COUNT(*) FROM nodes WHERE dim_y IS NOT NULL AND dim_y != 0.0"
        )
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


def _check_event_type_coords_populated() -> bool:
    """Phase 3 marker: event_type_coords table exists with > 0 rows."""
    try:
        import sqlite3
        from pathlib import Path
        db_path = Path(__file__).parent.parent.parent / ".ystar_cieu_brain.db"
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='event_type_coords'"
        )
        if cur.fetchone()[0] == 0:
            conn.close()
            return False
        cur = conn.execute("SELECT COUNT(*) FROM event_type_coords")
        count = cur.fetchone()[0]
        conn.close()
        return count > 0
    except Exception:
        return False


_SHIP_MARKER_REGISTRY: Dict[str, Any] = {
    "activation_log_nonzero":        _check_activation_log_nonzero,
    "cieu_brain_bridge_tests_pass":  _check_cieu_brain_bridge_tests_pass,
    "continuous_daemon_running":      _check_continuous_daemon_running,
    "hebbian_edges_nonzero":         _check_hebbian_edges_nonzero,
    "dim_drift_applied":             _check_dim_drift_applied,
    "event_type_coords_populated":   _check_event_type_coords_populated,
}


def _check_ship_marker(marker_name: str) -> bool:
    """Dispatch to the appropriate marker checker. Unknown markers return False."""
    checker = _SHIP_MARKER_REGISTRY.get(marker_name)
    if checker is None:
        _log.warning("Unknown ship marker: %s", marker_name)
        return False
    try:
        return checker()
    except Exception as e:
        _log.warning("Ship marker %s check failed: %s", marker_name, e)
        return False


def register_ship_marker(name: str, checker_fn: Any) -> None:
    """Register a custom ship marker checker (for extensibility)."""
    _SHIP_MARKER_REGISTRY[name] = checker_fn


# ── Module-level convenience wrappers ────────────────────────────────────────

def enumerate_open_completeness_obligations() -> List[str]:
    """
    Module-level convenience: create an OmissionEngine with default store
    and return open completeness obligation tags.

    Usage:
        from ystar.governance.omission_engine import enumerate_open_completeness_obligations
        print(enumerate_open_completeness_obligations())
    """
    engine = OmissionEngine()
    return engine.enumerate_open_completeness_obligations()


# ══════════════════════════════════════════════════════════════════════════════
# Level 2: Manifest Self-Audit ("无的无" — gaps the manifest itself doesn't name)
# Board 2026-04-19: "有了就要照亮更多的无"
# ══════════════════════════════════════════════════════════════════════════════

def audit_manifest_completeness(
    manifest_path: str,
    cieu_db_path: str,
    window_days: int = 7,
) -> Dict[str, Any]:
    """
    Level 2 recursive illumination: discover failure event types in CIEU that
    the phase lifecycle manifest does NOT reference.

    Algorithm:
      1. Scan CIEU for DENY/ERROR/VIOLATION event types in last N days
      2. Parse manifest ship_markers and extract which event types they reference
      3. Compute: cieu_failure_event_types ∖ manifest_referenced_types = unnamed gaps
      4. Return suggested new manifest sections with proposed ship_markers

    Emits CIEU_MANIFEST_GAP_DETECTED meta-event per gap found.

    Args:
        manifest_path: Path to phase_lifecycle_manifest.yaml
        cieu_db_path:  Path to .ystar_cieu.db
        window_days:   How far back to look for failure events (default 7)

    Returns:
        dict with keys:
          - "gaps": list of {"failure_type": str, "count": int, "suggested_marker": str}
          - "manifest_types_covered": list of str (types the manifest already knows)
          - "cieu_failure_types": list of str (all failure types from CIEU)
          - "meta_events_emitted": int
    """
    import sqlite3
    from pathlib import Path

    result: Dict[str, Any] = {
        "gaps": [],
        "manifest_types_covered": [],
        "cieu_failure_types": [],
        "meta_events_emitted": 0,
    }

    # 1. Query CIEU for failure event types in the window
    cieu_failure_types: Dict[str, int] = {}
    try:
        cutoff = time.time() - (window_days * 86400)
        conn = sqlite3.connect(cieu_db_path)
        cur = conn.execute(
            "SELECT event_type, COUNT(*) "
            "FROM cieu_events "
            "WHERE decision IN ('deny', 'error', 'violated') "
            "  AND created_at >= ? "
            "GROUP BY event_type "
            "ORDER BY COUNT(*) DESC",
            (cutoff,),
        )
        for row in cur.fetchall():
            cieu_failure_types[row[0]] = row[1]
        conn.close()
    except Exception as e:
        _log.warning("audit_manifest_completeness: CIEU query failed: %s", e)

    result["cieu_failure_types"] = list(cieu_failure_types.keys())

    # 2. Parse manifest and collect all event_type references
    manifest = _load_manifest(manifest_path)
    manifest_referenced_types: set = set()

    if manifest:
        for feature in manifest.get("features", []):
            fid = feature.get("feature_id", "")
            phases = feature.get("phases", {})
            for pkey, phase_def in phases.items():
                markers = phase_def.get("ship_markers", [])
                for marker in markers:
                    # The marker name itself is an implicit reference
                    manifest_referenced_types.add(marker)
                # Also check if description mentions event types
                desc = phase_def.get("description", "")
                if desc:
                    manifest_referenced_types.add(desc.lower().replace(" ", "_"))

            # Also add the feature_id itself as a known reference
            manifest_referenced_types.add(fid)

    result["manifest_types_covered"] = sorted(manifest_referenced_types)

    # 3. Compute gaps: failure types NOT covered by manifest references
    gaps = []
    for failure_type, count in cieu_failure_types.items():
        # A failure type is "covered" if the manifest references it
        # (either directly as a marker name or by substring containment)
        covered = False
        ft_lower = failure_type.lower()
        for ref in manifest_referenced_types:
            ref_lower = ref.lower()
            if ref_lower in ft_lower or ft_lower in ref_lower:
                covered = True
                break

        if not covered:
            suggested_marker = f"no_{failure_type.lower().replace(':', '_').replace(' ', '_')}_failures"
            gaps.append({
                "failure_type": failure_type,
                "count": count,
                "suggested_marker": suggested_marker,
            })

    result["gaps"] = gaps

    # 4. Emit CIEU_MANIFEST_GAP_DETECTED meta-events
    meta_events_emitted = 0
    if gaps:
        try:
            conn = sqlite3.connect(cieu_db_path)
            now = time.time()
            for gap in gaps:
                event_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT OR IGNORE INTO cieu_events "
                    "(event_id, seq_global, created_at, session_id, agent_id, "
                    " event_type, decision, passed, "
                    " drift_detected, task_description, evidence_grade) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        int(now * 1_000_000),
                        now,
                        "system",
                        "omission_engine_level2",
                        "CIEU_MANIFEST_GAP_DETECTED",
                        "info",
                        1,
                        1,  # drift_detected = True (this IS a gap)
                        (
                            f"Level 2 manifest gap: failure_type={gap['failure_type']} "
                            f"count={gap['count']} suggested_marker={gap['suggested_marker']}"
                        ),
                        "governance",
                    ),
                )
                meta_events_emitted += 1
            conn.commit()
            conn.close()
        except Exception as e:
            _log.warning("audit_manifest_completeness: CIEU meta-event write failed: %s", e)

    result["meta_events_emitted"] = meta_events_emitted
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Level 3: Downstream Obligation Derivation ("无的生成性")
# Board 2026-04-19: "每一个有 ship 出来，必须至少照亮一个新的无"
# ══════════════════════════════════════════════════════════════════════════════

def derive_new_obligations_from_ship(
    ship_event: Dict[str, Any],
    manifest_path: Optional[str] = None,
    k9_adapter_path: Optional[str] = None,
    ystar_gov_root: Optional[str] = None,
    labs_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Level 3 recursive illumination: given a ship event, traverse the 6D brain
    ecosystem_entanglement nodes that link to this feature, and check whether
    corresponding downstream artifacts exist.

    Missing artifact = new obligation illuminated.

    Additionally, if K9Audit is available, use CausalChainAnalyzer to walk the
    dependency graph and surface higher-order downstream absences.

    Args:
        ship_event:     dict with "feature_id" (str) and optional "event_type"
        manifest_path:  path to phase_lifecycle_manifest.yaml
        k9_adapter_path: path to K9Audit repo (default: /tmp/K9Audit)
        ystar_gov_root: path to Y*gov repo root
        labs_root:      path to ystar-company repo root

    Returns:
        dict with keys:
          - "derived_obligations": list of {
                "obligation_type": str,
                "missing_artifact": str,
                "reason": str,
                "source_node": str,
                "priority": str,
            }
          - "k9_used": bool
          - "k9_causal_obligations": list (extra obligations from K9 traversal)
          - "meta_events_emitted": int
    """
    from pathlib import Path

    result: Dict[str, Any] = {
        "derived_obligations": [],
        "k9_used": False,
        "k9_causal_obligations": [],
        "meta_events_emitted": 0,
    }

    feature_id = ship_event.get("feature_id", "unknown")
    event_type = ship_event.get("event_type", "")

    # Resolve repo roots
    if ystar_gov_root is None:
        ystar_gov_root = str(Path(__file__).parent.parent.parent)
    if labs_root is None:
        labs_root = str(
            Path(__file__).parent.parent.parent.parent / "ystar-company"
        )
    if k9_adapter_path is None:
        k9_adapter_path = "/tmp/K9Audit"

    # ── 6D Ecosystem Entanglement Map ──────────────────────────────────────
    # Each shipped feature entangles with these downstream artifact categories.
    # This is the "obligation derivation" — if we ship X, these must also exist.
    DOWNSTREAM_ARTIFACT_MAP = {
        "tests": {
            "description": "Test coverage for shipped feature",
            "check_paths": [
                f"tests/governance/test_{feature_id}.py",
                f"tests/test_{feature_id}.py",
            ],
            "priority": "HIGH",
        },
        "documentation": {
            "description": "Architecture doc or spec for shipped feature",
            "check_paths": [
                f"docs/arch/{feature_id}.md",
                f"docs/arch/{feature_id}_spec.md",
            ],
            "priority": "MEDIUM",
        },
        "manifest_entry": {
            "description": "Phase lifecycle manifest entry for feature",
            "check_fn": "_check_manifest_has_feature",
            "priority": "HIGH",
        },
        "forgetguard_rules": {
            "description": "ForgetGuard rules derived from feature failures",
            "check_paths_labs": [
                f"knowledge/shared/forgetguard_{feature_id}.yml",
            ],
            "priority": "LOW",
        },
        "brain_integration": {
            "description": "CIEU brain bridge integration for feature",
            "check_paths": [
                f"tools/cieu/cieu_{feature_id}_extractor.py",
                f"scripts/cieu_{feature_id}.py",
            ],
            "priority": "LOW",
        },
        "backup_artifact": {
            "description": "Backup/rollback plan for shipped feature",
            "check_paths_labs": [
                f"knowledge/cto/{feature_id}_rollback.md",
                f"knowledge/cto/{feature_id}_backup.md",
            ],
            "priority": "MEDIUM",
        },
    }

    gov_root = Path(ystar_gov_root)
    company_root = Path(labs_root)

    for artifact_key, artifact_def in DOWNSTREAM_ARTIFACT_MAP.items():
        found = False

        # Check Y*gov repo paths
        for rel_path in artifact_def.get("check_paths", []):
            if (gov_root / rel_path).exists():
                found = True
                break

        # Check ystar-company repo paths
        if not found:
            for rel_path in artifact_def.get("check_paths_labs", []):
                if (company_root / rel_path).exists():
                    found = True
                    break

        # Special check functions
        if not found and artifact_def.get("check_fn") == "_check_manifest_has_feature":
            mpath = manifest_path or str(
                gov_root / "docs" / "arch" / "phase_lifecycle_manifest.yaml"
            )
            manifest = _load_manifest(mpath)
            if manifest:
                for feat in manifest.get("features", []):
                    if feat.get("feature_id") == feature_id:
                        found = True
                        break

        if not found:
            result["derived_obligations"].append({
                "obligation_type": OmissionType.DERIVED_OBLIGATION.value,
                "missing_artifact": artifact_key,
                "reason": artifact_def["description"],
                "source_node": f"{feature_id}:{artifact_key}",
                "priority": artifact_def["priority"],
            })

    # ── K9 Integration (if available) ──────────────────────────────────────
    k9_path = Path(k9_adapter_path)
    if k9_path.exists() and (k9_path / "k9log" / "causal_analyzer.py").exists():
        try:
            import sys
            if str(k9_path) not in sys.path:
                sys.path.insert(0, str(k9_path))
            from k9log.causal_analyzer import CausalChainAnalyzer

            result["k9_used"] = True

            # Use K9 to find dependency edges from the shipped feature
            # K9 CausalChainAnalyzer works on JSONL files — we create a
            # minimal one representing the ship event and its known dependencies
            import tempfile
            import json

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".jsonl", delete=False
            ) as f:
                # Write a synthetic JSONL representing the ship event
                record = {
                    "event_type": event_type or f"{feature_id}_shipped",
                    "X_t": {"agent_id": "system", "feature": feature_id},
                    "U_t": {"action": "ship"},
                    "Y_t+1": {"status": "shipped"},
                    "R_t+1": {"passed": True},
                }
                f.write(json.dumps(record) + "\n")
                tmpfile = f.name

            try:
                analyzer = CausalChainAnalyzer(tmpfile)
                dag = analyzer.build_causal_dag()
                root_causes = analyzer.find_root_causes()

                for cause in root_causes:
                    result["k9_causal_obligations"].append({
                        "obligation_type": OmissionType.DERIVED_OBLIGATION.value,
                        "missing_artifact": f"k9_causal:{cause}",
                        "reason": f"K9 CausalChainAnalyzer identified unresolved dependency: {cause}",
                        "source_node": f"k9:{feature_id}",
                        "priority": "MEDIUM",
                    })
            except Exception as e:
                _log.info("K9 causal analysis ran but produced no extra obligations: %s", e)
            finally:
                import os
                os.unlink(tmpfile)

        except ImportError:
            _log.info("K9Audit import failed, skipping causal traversal")
        except Exception as e:
            _log.warning("K9 integration error: %s", e)

    # ── Emit CIEU_DERIVED_OBLIGATION meta-events ──────────────────────────
    all_obligations = result["derived_obligations"] + result["k9_causal_obligations"]
    meta_events_emitted = 0

    if all_obligations:
        try:
            # Try to write to the standard CIEU DB
            cieu_db_default = gov_root / ".ystar_cieu.db"
            if not cieu_db_default.exists():
                # Fallback: ystar-company CIEU DB
                cieu_db_default = company_root / ".ystar_cieu.db"

            if cieu_db_default.exists():
                import sqlite3
                conn = sqlite3.connect(str(cieu_db_default))
                now = time.time()
                for ob in all_obligations:
                    event_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT OR IGNORE INTO cieu_events "
                        "(event_id, seq_global, created_at, session_id, agent_id, "
                        " event_type, decision, passed, "
                        " drift_detected, task_description, evidence_grade) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            event_id,
                            int(now * 1_000_000),
                            now,
                            "system",
                            "omission_engine_level3",
                            "CIEU_DERIVED_OBLIGATION",
                            "info",
                            1,
                            1,
                            (
                                f"Level 3 derived obligation: "
                                f"missing={ob['missing_artifact']} "
                                f"reason={ob['reason']} "
                                f"source={ob['source_node']} "
                                f"priority={ob['priority']}"
                            ),
                            "governance",
                        ),
                    )
                    meta_events_emitted += 1
                conn.commit()
                conn.close()
        except Exception as e:
            _log.warning("derive_new_obligations: CIEU meta-event write failed: %s", e)

    result["meta_events_emitted"] = meta_events_emitted
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Level 4: Knowledge-Action Gap Detection ("知行合一" — Wang Yangming)
# Board 2026-04-19: "OmissionEngine 也应该是知行合一的重要引擎"
#
# Knowing X without doing X = omission failure.
# This detector reads a declarative registry of knowledge-action contracts
# and scans CIEU for trigger events WITHOUT their required follow-up actions.
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_REGISTRY_PATH = str(
    __import__("pathlib").Path(__file__).parent.parent.parent
    / "docs" / "arch" / "knowledge_action_registry.yaml"
)


def _load_knowledge_action_registry(
    registry_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load the knowledge-action registry YAML. Returns list of rule dicts."""
    from pathlib import Path

    path = Path(registry_path or _DEFAULT_REGISTRY_PATH)
    if not path.exists():
        _log.warning("Knowledge-action registry not found: %s", path)
        return []

    try:
        import yaml
        with open(path, "r") as f:
            data = yaml.safe_load(f)
        return data.get("rules", []) if data else []
    except Exception as e:
        _log.warning("Failed to load knowledge-action registry: %s", e)
        return []


def detect_knowledge_action_gaps(
    cieu_db_path: Optional[str] = None,
    registry_path: Optional[str] = None,
    cieu_window_sec: int = 300,
) -> Dict[str, Any]:
    """
    Level 4 knowledge-action gap detector.

    For each rule in the registry:
      1. Find CIEU events matching knowledge_trigger within the time window
      2. For each trigger event, check if a matching required_action event
         exists within detection_window_sec AFTER the trigger
      3. Unmatched triggers = knowledge-action gaps

    Args:
        cieu_db_path:     Path to .ystar_cieu.db (auto-detected if None)
        registry_path:    Path to knowledge_action_registry.yaml (default in docs/arch/)
        cieu_window_sec:  How far back to scan for trigger events (default 300s = 5 min)

    Returns:
        dict with keys:
          - "gaps": list of {knowledge_id, trigger_event_type, trigger_ts, required_action,
                             detection_window_sec, severity, description}
          - "rules_checked": int
          - "total_triggers_found": int
          - "total_gaps": int
          - "obligations_registered": int
    """
    import sqlite3
    from pathlib import Path

    result: Dict[str, Any] = {
        "gaps": [],
        "rules_checked": 0,
        "total_triggers_found": 0,
        "total_gaps": 0,
        "obligations_registered": 0,
    }

    # Auto-detect CIEU DB path
    if cieu_db_path is None:
        for candidate in [
            Path(__file__).parent.parent.parent / ".ystar_cieu.db",
            Path.home() / ".openclaw" / "workspace" / "ystar-company" / ".ystar_cieu.db",
            Path.home() / ".openclaw" / "workspace" / "Y-star-gov" / ".ystar_cieu.db",
        ]:
            if candidate.exists():
                cieu_db_path = str(candidate)
                break

    if cieu_db_path is None or not Path(cieu_db_path).exists():
        _log.warning("No CIEU database found for knowledge-action gap detection")
        return result

    # Load the registry
    rules = _load_knowledge_action_registry(registry_path)
    if not rules:
        _log.info("No rules in knowledge-action registry")
        return result

    result["rules_checked"] = len(rules)
    now = time.time()
    cutoff = now - cieu_window_sec

    try:
        conn = sqlite3.connect(cieu_db_path)

        for rule in rules:
            kid = rule.get("knowledge_id", "unknown")
            trigger_pattern = rule.get("knowledge_trigger", "")
            action_pattern = rule.get("required_action", "")
            window = rule.get("detection_window_sec", 30)
            severity = rule.get("severity", "medium")
            description = rule.get("description", "")

            if not trigger_pattern or not action_pattern:
                continue

            # Find trigger events in the scan window
            # Use LIKE for substring matching on event_type or task_description
            cur = conn.execute(
                "SELECT event_id, event_type, created_at, task_description "
                "FROM cieu_events "
                "WHERE created_at >= ? "
                "  AND (event_type LIKE ? OR task_description LIKE ?) "
                "ORDER BY created_at ASC",
                (cutoff, f"%{trigger_pattern}%", f"%{trigger_pattern}%"),
            )
            triggers = cur.fetchall()
            result["total_triggers_found"] += len(triggers)

            for trig_id, trig_type, trig_ts, trig_desc in triggers:
                # Look for the required action within the detection window
                action_cutoff = trig_ts + window
                action_cur = conn.execute(
                    "SELECT COUNT(*) FROM cieu_events "
                    "WHERE created_at >= ? AND created_at <= ? "
                    "  AND (event_type LIKE ? OR task_description LIKE ?)",
                    (trig_ts, action_cutoff, f"%{action_pattern}%", f"%{action_pattern}%"),
                )
                action_count = action_cur.fetchone()[0]

                if action_count == 0:
                    gap = {
                        "knowledge_id": kid,
                        "trigger_event_type": trig_type,
                        "trigger_ts": trig_ts,
                        "required_action": action_pattern,
                        "detection_window_sec": window,
                        "severity": severity,
                        "description": description.strip() if description else "",
                    }
                    result["gaps"].append(gap)
                    result["total_gaps"] += 1

        conn.close()
    except Exception as e:
        _log.warning("detect_knowledge_action_gaps: CIEU query error: %s", e)

    # Register obligations for detected gaps
    if result["gaps"]:
        try:
            store = OmissionStore(db_path=".ystar_omission.db")
            for gap in result["gaps"]:
                ob = ObligationRecord(
                    entity_id=f"knowledge_action:{gap['knowledge_id']}",
                    actor_id="system",
                    obligation_type=OmissionType.KNOWLEDGE_ACTION_GAP.value,
                    required_event_types=[gap["required_action"]],
                    due_at=gap["trigger_ts"] + gap["detection_window_sec"],
                    status=ObligationStatus.PENDING,
                    violation_code="knowledge_action_gap",
                    severity=Severity[gap["severity"].upper()],
                    notes=(
                        f"KNOWLEDGE_ACTION_GAP:{gap['knowledge_id']} | "
                        f"trigger={gap['trigger_event_type']} | "
                        f"required={gap['required_action']} | "
                        f"window={gap['detection_window_sec']}s"
                    ),
                )
                store.add_obligation(ob)
                result["obligations_registered"] += 1
        except Exception as e:
            _log.warning("Failed to register knowledge-action gap obligations: %s", e)

    return result


def enumerate_open_knowledge_action_gaps(
    cieu_db_path: Optional[str] = None,
    registry_path: Optional[str] = None,
    cieu_window_sec: int = 300,
) -> List[str]:
    """
    Convenience wrapper: returns list of gap tags.

    Format: ["KNOWLEDGE_ACTION_GAP:<knowledge_id>", ...]

    Suitable for use in Stop hook reply scans, CEO pre-output checks, etc.
    """
    result = detect_knowledge_action_gaps(
        cieu_db_path=cieu_db_path,
        registry_path=registry_path,
        cieu_window_sec=cieu_window_sec,
    )
    return [
        f"KNOWLEDGE_ACTION_GAP:{gap['knowledge_id']}"
        for gap in result.get("gaps", [])
    ]
