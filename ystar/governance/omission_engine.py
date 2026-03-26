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
    from ystar.omission_engine import OmissionEngine
    from ystar.governance.omission_store import InMemoryOmissionStore
    from ystar.governance.omission_rules import get_registry

    engine = OmissionEngine(store=InMemoryOmissionStore(), registry=get_registry())

    # 注入事件
    engine.ingest_event(ev)

    # 扫描过期义务（定时调用）
    violations = engine.scan()
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

from ystar.governance.omission_models import (
    EntityStatus, ObligationStatus, Severity,
    EscalationAction, EscalationPolicy,
    TrackedEntity, ObligationRecord, GovernanceEvent,
    OmissionViolation, GEventType, OmissionType,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore
from ystar.governance.omission_rules import RuleRegistry, get_registry
from ystar.governance.cieu_store import NullCIEUStore

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
        store: AnyStore,
        registry: Optional[RuleRegistry] = None,
        cieu_store: Any = None,          # CIEUStore | NullCIEUStore | None
        now_fn: Optional[Any] = None,    # Callable[[], float]
    ) -> None:
        self.store    = store
        self.registry = registry or get_registry()
        # [FIX-2] 用 NullCIEUStore 替代 None 作为默认值。
        # None 会导致 omission 违规静默丢失（_write_to_cieu 直接 return）。
        # NullCIEUStore 保持接口一致，同时发出 UserWarning 提醒配置缺失。
        self.cieu_store = cieu_store if cieu_store is not None else NullCIEUStore()
        self._now     = now_fn or time.time

    # ── 主入口 1：注入单个事件 ───────────────────────────────────────────────

    def ingest_event(self, ev: GovernanceEvent) -> EngineResult:
        """
        接收一个 GovernanceEvent：
          1. 存入 store
          2. 检查是否 fulfill 了任何 pending obligation
          3. 检查是否触发了新的 obligation（通过 rule matching）
          4. 返回 EngineResult
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
                if not self.store.violation_exists_for_obligation(ob.obligation_id):
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
                    if not self._hard_violation_exists(ob.obligation_id):
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
                if not self.store.violation_exists_for_obligation(ob.obligation_id):
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
            if not self._hard_violation_exists(ob.obligation_id):
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
        """
        fulfilled = []
        # check all open-status obligations (PENDING + SOFT_OVERDUE + HARD_OVERDUE)
        all_obs = self.store.list_obligations(entity_id=ev.entity_id)
        for ob in all_obs:
            if not ob.status.is_open:
                continue
            if ev.event_type in ob.required_event_types:
                ob.status = ObligationStatus.FULFILLED
                ob.fulfilled_by_event_id = ev.event_id
                self.store.update_obligation(ob)
                fulfilled.append(ob)
        return fulfilled

    # ── 私有：trigger ─────────────────────────────────────────────────────────

    def _trigger_obligations(self, ev: GovernanceEvent) -> List[ObligationRecord]:
        """
        检查事件是否触发任何 OmissionRule，并创建对应的 ObligationRecord。
        """
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

    # ── 私有：reminder ─────────────────────────────────────────────────────────

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
            }
            ok = self.cieu_store.write_dict(cieu_record)
            if ok:
                v.cieu_ref = cieu_record["event_id"]
        except Exception:
            pass  # CIEU 写入失败不阻断主流程

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
