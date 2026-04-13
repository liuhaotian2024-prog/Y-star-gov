# Layer: Foundation
"""
ystar.intervention_engine  —  Active Intervention Engine
=========================================================
v0.41.0

接收 OmissionViolation → 产生 InterventionPulse → 执行干预动作

三级干预触发条件：
  Level 1 (Soft Pulse)       ← soft_overdue violation
  Level 2 (Interrupt Gate)   ← hard_overdue violation
  Level 3 (Reroute/Escalate) ← escalated obligation 或 hard_overdue 持续

架构与 OmissionEngine 协同：
    OmissionEngine.scan() → violations → InterventionEngine.process_violations()
                                         → InterventionPulse
                                         → capability restrictions
                                         → CIEU records

Obligation-First Gate：
    适配层 enforce() 前调用 InterventionEngine.gate_check(actor_id, action_type)
    → 如果 actor 有 HARD_OVERDUE obligation → DENY 或 REDIRECT
    → 允许的动作仅限于 obligation fulfillment events
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Set, Union

from ystar.governance.intervention_models import (
    InterventionLevel, InterventionActionType, InterventionStatus,
    GateDecision, CapabilityRestriction,
    InterventionPulse, GateCheckResult, InterventionResult,
)
from ystar.governance.omission_models import (
    ObligationStatus, OmissionViolation, ObligationRecord,
    Severity, GEventType,
)
from ystar.governance.omission_store import InMemoryOmissionStore, OmissionStore

_log = logging.getLogger(__name__)

AnyStore = Union[InMemoryOmissionStore, OmissionStore]

# ══════════════════════════════════════════════════════════════════════════════
# P0: GatingPolicy — 可注入的 gate 策略合约
#
# 核心修复：把"哪些动作被 gate"从硬编码字符串集合升级为可注入的策略合约。
# Kernel 不预设任何生态专有字符串（如 "subagent_spawn"、"task_acked"）。
# 这些由 Ecosystem Adapter 通过 GatingPolicy.extend() 注入。
# ══════════════════════════════════════════════════════════════════════════════

from dataclasses import dataclass as _dc, field as _field
import copy as _copy

@_dc
class GatingPolicy:
    """
    定义 obligation-first gate 的行为策略合约。

    默认值只含 GEventType 常量（governance 通用语义）。
    生态专有动作名称由 Ecosystem Adapter 通过 extend() 注入。

    这是"宪法以代码为核心"的具体体现：
    不用 markdown 文档约定边界，用可测试的策略对象强制隔离。
    """
    # 义务履行类：永远 ALLOW（actor 无论何种状态都可以还债）
    fulfillment_action_types: Set[str] = _field(default_factory=lambda: {
        GEventType.ACKNOWLEDGEMENT_EVENT,
        GEventType.DECLINE_EVENT,
        GEventType.STATUS_UPDATE_EVENT,
        GEventType.BLOCKER_REPORT_EVENT,
        GEventType.RESULT_PUBLICATION_EVENT,
        GEventType.UPSTREAM_NOTIFY_EVENT,
        GEventType.ESCALATION_EVENT,
        GEventType.CLOSURE_EVENT,
        GEventType.COMPLETION_EVENT,
        GEventType.DELEGATION_EVENT,
        GEventType.SELF_OWNERSHIP_EVENT,
        GEventType.CLARIFICATION_EVENT,
        GEventType.OBLIGATION_RESTORED,  # v0.43: restoration 永远放行
    })

    # 高风险动作类：actor 有 hard_overdue 时 DENY
    # 默认用治理语义表达（创建实体、分配责任）
    high_risk_action_types: Set[str] = _field(default_factory=lambda: {
        GEventType.ENTITY_CREATED,
        GEventType.ENTITY_ASSIGNED,
    })

    def allows(self, action_type: str) -> bool:
        return action_type in self.fulfillment_action_types

    def is_high_risk(self, action_type: str) -> bool:
        return action_type in self.high_risk_action_types

    def extend(
        self,
        fulfillment: Optional[Set[str]] = None,
        high_risk: Optional[Set[str]] = None,
    ) -> "GatingPolicy":
        """
        返回扩展后的新 GatingPolicy（不可变风格）。
        Ecosystem Adapter 用此方法注入生态专有动作名称。

        适配层注入示例（以下字符串由适配层定义，治理核心不预设）：
            policy = GatingPolicy().extend(
                fulfillment={"ack_event", "status_update", "result_published"},
                high_risk={"spawn_action", "handoff_action", "write_action", "exec_action"},
            )
        """
        new_policy = _copy.deepcopy(self)
        if fulfillment:
            new_policy.fulfillment_action_types |= fulfillment
        if high_risk:
            new_policy.high_risk_action_types |= high_risk
        return new_policy


# 默认策略：只含 governance 通用语义，无生态专有字符串
DEFAULT_GATING_POLICY = GatingPolicy()

# 向后兼容别名（现有测试用这两个名字）
_OBLIGATION_FULFILLMENT_ACTIONS = DEFAULT_GATING_POLICY.fulfillment_action_types
_HIGH_RISK_ACTIONS               = DEFAULT_GATING_POLICY.high_risk_action_types


# ── Pulse 内存存储（轻量，不持久化到 SQLite）─────────────────────────────────

class PulseStore:
    """
    InterventionPulse 的内存存储。
    足够轻量：pulse 生命周期短，resolved 后清理。

    v0.41 内存泄漏修复：
    - _MAX_RESOLVED: 已解决 pulse 的保留上限，超出后按时间清理最老的
    - gc_resolved(): 主动 GC，由 add_pulse() 在写入时触发
    - stats(): 返回内存占用摘要，供 ystar doctor 使用
    """

    _MAX_RESOLVED = 1000  # 已解决 pulse 最多保留 1000 条

    def __init__(self) -> None:
        self._pulses: Dict[str, InterventionPulse] = {}
        self._restrictions: Dict[str, CapabilityRestriction] = {}  # actor_id → restriction

    def add_pulse(self, p: InterventionPulse) -> None:
        self._pulses[p.pulse_id] = p
        # 每次写入时检查是否需要 GC（避免无限增长）
        self._gc_resolved_if_needed()

    def _gc_resolved_if_needed(self) -> int:
        """
        如果已解决 pulse 超过上限，清理最老的一批。
        返回清理的数量。
        v0.41: 解决长时间运行 session 的内存泄漏问题。
        """
        resolved = [p for p in self._pulses.values()
                    if p.status != InterventionStatus.ACTIVE]
        if len(resolved) <= self._MAX_RESOLVED:
            return 0
        # 按 resolved_at 排序，删除最老的一半
        resolved.sort(key=lambda p: getattr(p, "resolved_at", 0) or 0)
        to_delete = resolved[:len(resolved) // 2]
        for p in to_delete:
            self._pulses.pop(p.pulse_id, None)
        return len(to_delete)

    def gc_resolved(self) -> int:
        """手动触发 GC（供外部调用，如 ystar doctor）。返回清理数量。"""
        resolved = [p for p in self._pulses.values()
                    if p.status != InterventionStatus.ACTIVE]
        for p in resolved:
            self._pulses.pop(p.pulse_id, None)
        return len(resolved)

    def stats(self) -> dict:
        """返回内存占用摘要，供 ystar doctor 诊断。"""
        active   = sum(1 for p in self._pulses.values()
                       if p.status == InterventionStatus.ACTIVE)
        resolved = len(self._pulses) - active
        return {
            "total":       len(self._pulses),
            "active":      active,
            "resolved":    resolved,
            "restrictions": len(self._restrictions),
        }

    def get_pulse(self, pulse_id: str) -> Optional[InterventionPulse]:
        return self._pulses.get(pulse_id)

    def update_pulse(self, p: InterventionPulse) -> None:
        self._pulses[p.pulse_id] = p

    def active_pulses_for_actor(self, actor_id: str) -> List[InterventionPulse]:
        return [p for p in self._pulses.values()
                if p.actor_id == actor_id and p.status == InterventionStatus.ACTIVE]

    def active_pulses_for_entity(self, entity_id: str) -> List[InterventionPulse]:
        return [p for p in self._pulses.values()
                if p.entity_id == entity_id and p.status == InterventionStatus.ACTIVE]

    def pulse_exists(self, obligation_id: str, level: InterventionLevel) -> bool:
        return any(
            p.trigger_obligation_id == obligation_id
            and p.level == level
            and p.status == InterventionStatus.ACTIVE
            for p in self._pulses.values()
        )

    def set_restriction(self, r: CapabilityRestriction) -> None:
        self._restrictions[r.actor_id] = r

    def get_restriction(self, actor_id: str) -> Optional[CapabilityRestriction]:
        r = self._restrictions.get(actor_id)
        return r if (r and r.active) else None

    def clear_restriction(self, actor_id: str) -> bool:
        r = self._restrictions.get(actor_id)
        if r and r.active:
            r.active = False
            r.resolved_at = time.time()
            r.resolved_reason = "obligation_fulfilled"
            return True
        return False

    def all_pulses(self) -> List[InterventionPulse]:
        return list(self._pulses.values())


# ── InterventionEngine ───────────────────────────────────────────────────────


def _build_suggested_action(
    ob: "Optional[Any]",
    pulse: "Any",
    urgency: str,
) -> str:
    """
    构建 gate_check 返回给 agent 的 suggested_action 字符串。
    包含：义务类型、所需事件、超时时长、建议行动。
    """
    import time as _time
    if ob is None:
        return f"[{urgency}] Fulfill obligation: {pulse.omission_type}"

    required = getattr(ob, "required_event_types", [])
    overdue  = max(0.0, _time.time() - (ob.effective_due_at or _time.time()))
    notes    = getattr(ob, "notes", "") or ""

    lines = [
        f"[{urgency}] Obligation overdue: {ob.obligation_type}",
        f"  Required action(s): {', '.join(required) if required else 'fulfill obligation'}",
        f"  Overdue by: {overdue:.0f}s",
    ]
    if notes:
        lines.append(f"  Context: {notes[:120]}")
    lines.append("  → Complete the required action to unblock.")
    return "\n".join(lines)

class InterventionEngine:
    """
    主动干预引擎。

    核心职责：
      1. process_violations()  —— 将 omission violations 转为干预脉冲
      2. gate_check()          —— obligation-first gating（在 enforce() 前调用）
      3. resolve_for_actor()   —— actor 履行义务后解除干预
      4. scan_restorations()   —— 扫描可恢复权限的 actor
    """

    def __init__(
        self,
        omission_store: AnyStore,
        cieu_store: Optional[Any] = None,
        now_fn: Optional[Callable[[], float]] = None,
        # 干预触发配置
        soft_pulse_on_soft_overdue: bool = True,
        interrupt_gate_on_hard_overdue: bool = True,
        reroute_on_escalated: bool = True,
        # 默认 fallback / escalate 配置
        default_escalate_to: Optional[str] = None,
        default_fallback_owner: Optional[str] = None,
        gating_policy:         Optional["GatingPolicy"] = None,
        causal_engine:         Optional[Any] = None,
    ) -> None:
        self.omission_store              = omission_store
        self.cieu_store                  = cieu_store
        self._now                        = now_fn or time.time
        self.pulse_store                 = PulseStore()

        # 触发配置
        self.soft_pulse_on_soft_overdue  = soft_pulse_on_soft_overdue
        self.interrupt_gate_on_hard_overdue = interrupt_gate_on_hard_overdue
        self.reroute_on_escalated        = reroute_on_escalated

        self.default_escalate_to         = default_escalate_to
        self.default_fallback_owner      = default_fallback_owner
        # P0: gating 策略（引擎本身不硬编码任何生态字符串）
        self.gating_policy = gating_policy if gating_policy is not None                              else DEFAULT_GATING_POLICY
        # GAP 4 FIX: Optional causal engine for advisory recommendations
        self.causal_engine = causal_engine

        # ── Circuit breaker state ──────────────────────────────────────
        # P0: 防止 violation 雪球效应。
        # B1 fix 2026-04-12: 从"累积永不衰减"改为"滑动窗口"——
        # 只有在 window_secs 内累计 >= threshold 次违规才 ARM，
        # 响应"持续高违规率"而非"历史总量"。
        self._circuit_breaker_armed = False
        self._circuit_breaker_threshold = 50
        self._circuit_breaker_window_secs = 600  # 10 min 滑动窗口
        # List of (timestamp, violation_count) tuples inside window
        self._circuit_breaker_window: list = []
        # Total within window — derived, kept for CIEU log compatibility
        self._circuit_breaker_violation_count = 0

    # ── 主入口 1：处理 omission violations → 产生干预脉冲 ────────────────────

    def process_violations(
        self,
        violations: List[OmissionViolation],
    ) -> InterventionResult:
        """
        接收 OmissionEngine.scan() 输出的 violation 列表，
        根据严重程度产生对应级别的干预脉冲。
        """
        result = InterventionResult()
        now = self._now()

        # ── Circuit breaker: 滑动窗口计数 ────────────────────────────
        # B1 fix: 旧逻辑 `count += len(violations)` 永不衰减，
        # 累积到 threshold 后 ARM 且无法自恢复。改用滑动窗口：
        # 超出 window_secs 的历史违规自动淘汰。
        cutoff = now - self._circuit_breaker_window_secs
        self._circuit_breaker_window = [
            (ts, c) for ts, c in self._circuit_breaker_window if ts > cutoff
        ]
        if violations:
            self._circuit_breaker_window.append((now, len(violations)))
        self._circuit_breaker_violation_count = sum(
            c for _, c in self._circuit_breaker_window
        )

        if (self._circuit_breaker_violation_count >= self._circuit_breaker_threshold
                and not self._circuit_breaker_armed):
            self._circuit_breaker_armed = True
            if self.cieu_store:
                try:
                    self.cieu_store.write_dict({
                        "event_id":     str(uuid.uuid4()),
                        "seq_global":   int(now * 1_000_000),
                        "created_at":   now,
                        "session_id":   "circuit_breaker",
                        "agent_id":     "intervention_engine",
                        "event_type":   "circuit_breaker_armed",
                        "decision":     "deny",
                        "passed":       False,
                        "violations":   [],
                        "task_description": (
                            f"Circuit breaker ARMED: "
                            f"{self._circuit_breaker_violation_count} violations "
                            f"reached threshold {self._circuit_breaker_threshold}"
                        ),
                        "evidence_grade": "governance",
                    })
                except Exception as e:
                    _log.error("Failed to write circuit_breaker_armed to CIEU: %s", e)
            _log.warning(
                "Circuit breaker ARMED: %d violations reached threshold %d. "
                "Pulse generation STOPPED.",
                self._circuit_breaker_violation_count,
                self._circuit_breaker_threshold,
            )

        if self._circuit_breaker_armed:
            _log.debug(
                "Circuit breaker armed, %d violations rejected (total: %d)",
                len(violations),
                self._circuit_breaker_violation_count,
            )
            return result  # 空 result — 不产生任何 pulse

        for v in violations:
            ob = self.omission_store.get_obligation(v.obligation_id)
            if ob is None:
                continue

            stage = v.details.get("stage", "soft_overdue")

            # ── Level 1: Soft Pulse（soft_overdue）──────────────────────
            if (self.soft_pulse_on_soft_overdue
                    and stage != "hard_overdue"
                    and not self.pulse_store.pulse_exists(
                        ob.obligation_id, InterventionLevel.SOFT_PULSE
                    )):
                pulse = self._make_soft_pulse(ob, v, now)
                self.pulse_store.add_pulse(pulse)
                self._write_pulse_to_cieu(pulse)
                result.pulses_fired.append(pulse)

            # ── Level 2: Interrupt Gate（hard_overdue）───────────────────
            elif (self.interrupt_gate_on_hard_overdue
                      and stage == "hard_overdue"
                      and not self.pulse_store.pulse_exists(
                          ob.obligation_id, InterventionLevel.INTERRUPT_GATE
                      )):
                pulse = self._make_interrupt_pulse(ob, v, now)
                self.pulse_store.add_pulse(pulse)
                self._write_pulse_to_cieu(pulse)
                result.pulses_fired.append(pulse)

                # 顺带创建 capability restriction
                restriction = self._make_capability_restriction(ob, pulse)
                self.pulse_store.set_restriction(restriction)
                result.capability_restrictions.append(restriction)

            # ── Level 3: Reroute（escalated obligation）──────────────────
            if (self.reroute_on_escalated
                    and ob.escalated
                    and not self.pulse_store.pulse_exists(
                        ob.obligation_id, InterventionLevel.REROUTE_ESCALATE
                    )):
                pulse = self._make_reroute_pulse(ob, v, now)
                self.pulse_store.add_pulse(pulse)
                self._write_pulse_to_cieu(pulse)
                result.pulses_fired.append(pulse)
                reroute_info = {
                    "entity_id":   ob.entity_id,
                    "actor_id":    ob.actor_id,
                    "escalate_to": pulse.escalate_to,
                    "fallback":    pulse.fallback_owner,
                    "pulse_id":    pulse.pulse_id,
                    "new_obligation_id": None,
                }
                # B5: Execute actual fallback reroute
                # Create a new obligation on the fallback owner / escalation target
                new_ob = self._execute_reroute(ob, pulse, now)
                if new_ob is not None:
                    reroute_info["new_obligation_id"] = new_ob.obligation_id
                result.reroutes.append(reroute_info)

        return result

    # ── 主入口 2：Obligation-First Gate（在 enforce() 之前调用）───────────────

    @staticmethod
    def _validate_agent_identity(actor_id: str) -> Optional[str]:
        """
        [Constitutional Rule] Validate agent identity is specific, not generic.

        Generic identities that should be rejected:
        - 'agent' (default/placeholder)
        - 'main' (bootstrap/temporary)
        - 'test_agent' (should only be used in test mode)
        - Any 32-char hex string (session IDs, not agent identities)

        Returns: None if valid, error message if invalid.
        """
        FORBIDDEN_IDENTITIES = {"agent", "main", "test_agent", "unknown", ""}

        if not actor_id or actor_id in FORBIDDEN_IDENTITIES:
            return f"DENIED: agent_id='{actor_id}' is generic/placeholder. Use specific agent identity."

        # Block raw session IDs (32-char hex strings like a8fbbc96648c1ac26)
        if len(actor_id) == 32 and all(c in "0123456789abcdef" for c in actor_id.lower()):
            return f"DENIED: agent_id='{actor_id}' appears to be a session ID, not an agent identity."

        return None

    def gate_check(
        self,
        actor_id: str,
        action_type: str,
        entity_id: Optional[str] = None,
    ) -> GateCheckResult:
        """
        检查该 actor 是否允许执行 action_type。

        规则：
        - 如果 action_type 是义务履行类事件 → ALLOW（永远放行，优先级最高）
        - [NEW] 如果 actor_id 是 generic placeholder → DENY（必须有明确身份）
        - 如果 actor 有 HARD_OVERDUE obligation + action 是高风险 → DENY/REDIRECT
        - 其他情况 → ALLOW

        设计意图：不让 actor 一边拖着 hard_overdue 义务不做，
                   一边继续执行 spawn/write/exec 等高影响动作。
        """
        # 义务履行动作永远允许（优先级最高，跳过身份检查）
        if self.gating_policy.allows(action_type):
            result = GateCheckResult(
                decision=GateDecision.ALLOW,
                actor_id=actor_id,
                action_type=action_type,
            )
            self._attach_causal_recommendation(result)
            return result

        # [Constitutional Rule #1] Agent identity must be specific
        identity_error = self._validate_agent_identity(actor_id)
        if identity_error:
            result = GateCheckResult(
                decision=GateDecision.DENY,
                actor_id=actor_id,
                action_type=action_type,
                blocking_omission_type=identity_error,
                suggested_action="Use specific agent identity (e.g., ystar-ceo, path_a_agent)",
            )
            self._record_gate_check(result, entity_id)
            return result

        # 检查是否有 active INTERRUPT_GATE pulse（= actor 有 hard_overdue）
        actor_pulses = self.pulse_store.active_pulses_for_actor(actor_id)
        hard_pulses = [p for p in actor_pulses
                       if p.level == InterventionLevel.INTERRUPT_GATE]

        if not hard_pulses:
            result = GateCheckResult(
                decision=GateDecision.ALLOW,
                actor_id=actor_id,
                action_type=action_type,
            )
            self._attach_causal_recommendation(result)
            return result

        # actor 有 hard overdue，检查 action 是否高风险
        most_urgent = hard_pulses[0]
        ob = self.omission_store.get_obligation(most_urgent.trigger_obligation_id)
        overdue = self._now() - (ob.effective_due_at or self._now()) if ob else 0.0

        if self.gating_policy.is_high_risk(action_type):
            result = GateCheckResult(
                decision=GateDecision.DENY,
                actor_id=actor_id,
                action_type=action_type,
                blocking_obligation_id=most_urgent.trigger_obligation_id,
                blocking_omission_type=most_urgent.omission_type,
                overdue_secs=max(overdue, 0),
                suggested_action=_build_suggested_action(ob, most_urgent, "REQUIRED"),
                pulse_id=most_urgent.pulse_id,
            )
            self._attach_causal_recommendation(result)
            return result
        else:
            # Non-critical action: redirect (warn but allow with caveat)
            result = GateCheckResult(
                decision=GateDecision.REDIRECT,
                actor_id=actor_id,
                action_type=action_type,
                blocking_obligation_id=most_urgent.trigger_obligation_id,
                blocking_omission_type=most_urgent.omission_type,
                overdue_secs=max(overdue, 0),
                suggested_action=_build_suggested_action(ob, most_urgent, "RECOMMENDED"),
                pulse_id=most_urgent.pulse_id,
            )
            self._attach_causal_recommendation(result)
            return result

    # ── 主入口 3：actor 履行义务后解除干预 ───────────────────────────────────

    def resolve_for_actor(
        self,
        actor_id: str,
        fulfilled_obligation_id: str,
        resolved_by_event_id: Optional[str] = None,
    ) -> List[InterventionPulse]:
        """
        当 actor 履行了 obligation 后，解除相关干预脉冲和权限限制。
        由 OmissionEngine._try_fulfill() 触发（通过 callback 或显式调用）。
        """
        now = self._now()
        resolved = []
        for pulse in self.pulse_store.active_pulses_for_actor(actor_id):
            if pulse.trigger_obligation_id == fulfilled_obligation_id:
                pulse.status               = InterventionStatus.RESOLVED
                pulse.resolved_at          = now
                pulse.resolved_by_event_id = resolved_by_event_id
                self.pulse_store.update_pulse(pulse)
                resolved.append(pulse)
        # 解除权限限制
        self.pulse_store.clear_restriction(actor_id)
        return resolved

    # ── 主入口 4：扫描可恢复权限 ─────────────────────────────────────────────

    def scan_restorations(self) -> List[str]:
        """
        扫描所有有 capability restriction 的 actor，
        如果其 hard_overdue obligations 都已 fulfilled/resolved，则恢复权限。
        返回被恢复的 actor_id 列表。
        """
        restored = []
        for pulse in self.pulse_store.all_pulses():
            if (pulse.level != InterventionLevel.INTERRUPT_GATE
                    or pulse.status != InterventionStatus.ACTIVE):
                continue
            ob = self.omission_store.get_obligation(pulse.trigger_obligation_id)
            if ob and not ob.status.is_open:
                self.pulse_store.clear_restriction(pulse.actor_id)
                pulse.status    = InterventionStatus.RESOLVED
                pulse.resolved_at = self._now()
                self.pulse_store.update_pulse(pulse)
                restored.append(pulse.actor_id)
        return restored

    # ── Circuit breaker reset ────────────────────────────────────────────────

    def reset_circuit_breaker(self) -> None:
        """
        Reset circuit breaker after manual intervention.
        Called by 'ystar reset-breaker' CLI command.
        """
        old_count = self._circuit_breaker_violation_count
        self._circuit_breaker_armed = False
        self._circuit_breaker_violation_count = 0
        self._circuit_breaker_window = []

        if self.cieu_store:
            try:
                now = self._now()
                self.cieu_store.write_dict({
                    "event_id":     str(uuid.uuid4()),
                    "seq_global":   int(now * 1_000_000),
                    "created_at":   now,
                    "session_id":   "circuit_breaker",
                    "agent_id":     "intervention_engine",
                    "event_type":   "circuit_breaker_reset",
                    "decision":     "allow",
                    "passed":       True,
                    "violations":   [],
                    "task_description": (
                        f"Circuit breaker RESET (was at {old_count} violations)"
                    ),
                    "evidence_grade": "governance",
                })
            except Exception as e:
                _log.error("Failed to write circuit_breaker_reset to CIEU: %s", e)

        _log.info("Circuit breaker reset (was at %d violations)", old_count)

    # ── 汇总 ─────────────────────────────────────────────────────────────────

    def intervention_report(self, actor_id: Optional[str] = None) -> dict:
        """返回当前干预状态快照。"""
        if actor_id:
            pulses = self.pulse_store.active_pulses_for_actor(actor_id)
            restriction = self.pulse_store.get_restriction(actor_id)
        else:
            pulses = [p for p in self.pulse_store.all_pulses()
                      if p.status == InterventionStatus.ACTIVE]
            restriction = None

        by_level: Dict[str, int] = {}
        for p in pulses:
            by_level[p.level.value] = by_level.get(p.level.value, 0) + 1

        return {
            "scope":        actor_id or "global",
            "active_pulses":len(pulses),
            "by_level":     by_level,
            "restricted":   bool(restriction or
                               any(self.pulse_store.get_restriction(p.actor_id)
                                   for p in pulses)),
            "pulses":       [p.to_dict() for p in pulses[:20]],  # cap at 20
        }

    # ── 主入口 5：主动改道查询 ───────────────────────────────────────────────

    def pending_reroutes(self) -> List[dict]:
        """返回所有已触发但未解决的 reroute 记录。"""
        return [
            {
                "pulse_id":    p.pulse_id,
                "entity_id":   p.entity_id,
                "from_actor":  p.actor_id,
                "escalate_to": p.escalate_to,
                "fallback":    p.fallback_owner,
                "triggered_at":p.triggered_at,
                "omission":    p.omission_type,
            }
            for p in self.pulse_store.all_pulses()
            if p.level == InterventionLevel.REROUTE_ESCALATE
            and p.status == InterventionStatus.ACTIVE
        ]

    # ── GAP 4 FIX: Causal advisory recommendation ─────────────────────────────

    def _attach_causal_recommendation(self, result: GateCheckResult) -> None:
        """
        If causal_engine is available, compute P(Health|do(block)) vs P(Health|do(allow))
        and attach as advisory recommendation. Does NOT change the gate decision.
        """
        if self.causal_engine is None:
            return
        try:
            # Use do_wire_query to estimate health impact of blocking vs allowing
            p_health_block = self.causal_engine.do_wire_query(wire=False)
            p_health_allow = self.causal_engine.do_wire_query(wire=True)
            if p_health_block is not None and p_health_allow is not None:
                if p_health_block > p_health_allow:
                    result.causal_recommendation = (
                        f"causal: block recommended "
                        f"(P(H|block)={p_health_block:.2f} > P(H|allow)={p_health_allow:.2f})"
                    )
                else:
                    result.causal_recommendation = (
                        f"causal: allow recommended "
                        f"(P(H|allow)={p_health_allow:.2f} >= P(H|block)={p_health_block:.2f})"
                    )
        except Exception as e:
            _log.warning("Causal gate check failed for actor %s: %s", actor_id, e)

    # ── 私有：脉冲工厂 ────────────────────────────────────────────────────────

    def _execute_reroute(
        self,
        ob: ObligationRecord,
        pulse: InterventionPulse,
        now: float,
    ) -> Optional[ObligationRecord]:
        """
        B5: 实际执行改道 — 在 fallback/escalation actor 上创建新义务。
        原义务由 ob (actor=lazy_actor) 转移到 fallback_owner 或 escalate_to。
        """
        new_actor = pulse.fallback_owner or pulse.escalate_to
        if not new_actor:
            return None
        try:
            from ystar.governance.omission_models import ObligationRecord as _OR, ObligationStatus as _OS
            new_ob = _OR(
                entity_id            = ob.entity_id,
                actor_id             = new_actor,
                obligation_type      = ob.obligation_type + "_rerouted",
                trigger_event_id     = ob.obligation_id,  # original ob as trigger
                required_event_types = ob.required_event_types,
                due_at               = now + 300.0,    # 5 min to respond
                grace_period_secs    = 60.0,
                status               = _OS.PENDING,
                violation_code       = ob.violation_code + "_rerouted",
                severity             = ob.severity,
                escalation_policy    = ob.escalation_policy,
                notes                = (
                    f"rerouted from actor='{ob.actor_id}' "
                    f"via pulse='{pulse.pulse_id}'"
                ),
            )
            self.omission_store.add_obligation(new_ob)
            return new_ob
        except Exception as e:
            _log.error("Failed to create reroute obligation for actor %s: %s", actor_id, e)
            return None

    def _make_soft_pulse(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
        now: float,
    ) -> InterventionPulse:
        return InterventionPulse(
            entity_id             = ob.entity_id,
            actor_id              = ob.actor_id,
            trigger_obligation_id = ob.obligation_id,
            omission_type         = ob.obligation_type,
            level                 = InterventionLevel.SOFT_PULSE,
            actions               = [
                InterventionActionType.SEND_REMINDER,
                InterventionActionType.OBLIGATION_FIRST_PROMPT,
            ],
            triggered_at          = now,
            details               = {
                "overdue_secs": v.overdue_secs,
                "obligation_type": ob.obligation_type,
                "required_events": ob.required_event_types,
            },
        )

    def _make_interrupt_pulse(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
        now: float,
    ) -> InterventionPulse:
        return InterventionPulse(
            entity_id             = ob.entity_id,
            actor_id              = ob.actor_id,
            trigger_obligation_id = ob.obligation_id,
            omission_type         = ob.obligation_type,
            level                 = InterventionLevel.INTERRUPT_GATE,
            actions               = [
                InterventionActionType.GATE_DENY,
                InterventionActionType.CAPABILITY_RESTRICT,
            ],
            triggered_at          = now,
            details               = {
                "overdue_secs":  v.overdue_secs,
                "stage":         "hard_overdue",
                "blocked_actions": list(_HIGH_RISK_ACTIONS),
            },
        )

    def _make_reroute_pulse(
        self,
        ob: ObligationRecord,
        v: OmissionViolation,
        now: float,
    ) -> InterventionPulse:
        escalate_to  = (ob.escalation_policy.escalate_to
                        or self.default_escalate_to
                        or "principal")
        fallback     = self.default_fallback_owner
        actions      = [InterventionActionType.ESCALATE_TO_PRINCIPAL]
        if fallback:
            actions.append(InterventionActionType.FALLBACK_OWNER)

        return InterventionPulse(
            entity_id             = ob.entity_id,
            actor_id              = ob.actor_id,
            trigger_obligation_id = ob.obligation_id,
            omission_type         = ob.obligation_type,
            level                 = InterventionLevel.REROUTE_ESCALATE,
            actions               = actions,
            triggered_at          = now,
            escalate_to           = escalate_to,
            fallback_owner        = fallback,
            details               = {
                "overdue_secs":  v.overdue_secs,
                "escalated_to":  escalate_to,
                "fallback_owner":fallback,
            },
        )

    def _make_capability_restriction(
        self,
        ob: ObligationRecord,
        pulse: InterventionPulse,
    ) -> CapabilityRestriction:
        return CapabilityRestriction(
            actor_id              = ob.actor_id,
            entity_id             = ob.entity_id,
            trigger_obligation_id = ob.obligation_id,
            restricted_actions    = list(self.gating_policy.high_risk_action_types),
            restricted_scopes     = ["spawn", "write", "exec"],
        )

    # ── 私有：CIEU 写入 ───────────────────────────────────────────────────────

    def _record_gate_check(
        self,
        result: GateCheckResult,
        entity_id: Optional[str] = None,
    ) -> None:
        """
        Record gate check result to CIEU for audit trail.
        Only records DENY decisions (ALLOW would spam the log).
        """
        if self.cieu_store is None:
            return
        if result.decision == GateDecision.ALLOW:
            return  # Don't spam CIEU with every successful gate check

        try:
            record = {
                "event_id":   str(uuid.uuid4()),
                "seq_global": int(self._now() * 1_000_000),
                "created_at": self._now(),
                "session_id": entity_id or "gate_check",
                "agent_id":   result.actor_id,
                "event_type": f"intervention_gate:{result.decision.value}",
                "decision":   result.decision.value,
                "passed":     result.decision == GateDecision.ALLOW,
                "violations": [{
                    "dimension":  "agent_identity_governance",
                    "field":      "actor_id",
                    "message":    result.blocking_omission_type or "Gate check failed",
                    "actual":     result.actor_id,
                    "constraint": "specific_agent_identity_required",
                    "severity":   1.0,  # Critical violation
                }],
                "drift_detected": True,
                "drift_details":  f"gate_decision={result.decision.value}",
                "drift_category": "identity_violation",
                "task_description": (
                    f"Gate: {result.decision.value} | "
                    f"action={result.action_type} | actor={result.actor_id}"
                ),
                "evidence_grade": "governance",
            }
            self.cieu_store.write_dict(record)
        except Exception as e:
            _log.error(
                "Failed to write gate check to CIEU (actor=%s, action=%s): %s",
                result.actor_id, result.action_type, e
            )

    def _write_pulse_to_cieu(self, pulse: InterventionPulse) -> None:
        if self.cieu_store is None:
            return
        try:
            record = {
                "event_id":   str(uuid.uuid4()),
                "seq_global": int(self._now() * 1_000_000),
                "created_at": self._now(),
                "session_id": pulse.entity_id,
                "agent_id":   pulse.actor_id,
                "event_type": f"intervention_pulse:{pulse.level.value}",
                "decision":   "escalate" if pulse.level != InterventionLevel.SOFT_PULSE
                              else "allow",
                "passed":     False,
                "violations": [{
                    "dimension":  "intervention_governance",
                    "field":      "obligation_unfulfilled",
                    "message":    (
                        f"[{pulse.level.value}] {pulse.omission_type}: "
                        f"actor '{pulse.actor_id}' — "
                        f"actions={[a.value for a in pulse.actions]}"
                    ),
                    "actual":     "hard_overdue" if pulse.level == InterventionLevel.INTERRUPT_GATE
                                  else "soft_overdue",
                    "constraint": f"obligation_id={pulse.trigger_obligation_id}",
                    "severity":   0.9 if pulse.level == InterventionLevel.INTERRUPT_GATE else 0.5,
                }],
                "drift_detected": True,
                "drift_details":  f"intervention_level={pulse.level.value}",
                "drift_category": "intervention_pulse",
                "task_description": (
                    f"Intervention: {pulse.level.value} | "
                    f"entity={pulse.entity_id} | actor={pulse.actor_id}"
                ),
                "evidence_grade": "governance",  # [P2-3] intervention 是治理级证据
            }
            ok = self.cieu_store.write_dict(record)
            if ok:
                pulse.cieu_ref = record["event_id"]
                self.pulse_store.update_pulse(pulse)
        except Exception as e:
            _log.error("Failed to write intervention pulse to CIEU (pulse_id=%s): %s", pulse.pulse_id, e)

    # ── L3.3: Circuit Breaker Auto-Reset ──────────────────────────────────────

    def auto_reset_circuit_breakers(
        self,
        agent_id: str,
        evidence: str,
        now: Optional[float] = None
    ) -> int:
        """
        AMENDMENT-015 Layer 3.3: Auto-reset circuit breakers when agent delivers observable action.

        Returns: number of restrictions lifted

        Example: Agent was blocked for missing test. Git commit arrives → auto-reset breaker.
        This eliminates 1739→<100 false-positive hard blocks.
        """
        if now is None:
            now = self._now()

        # Check if agent has active restrictions
        restriction = self.pulse_store.get_restriction(agent_id)
        if not restriction:
            return 0

        lifted = 0

        # Find all pulses for this agent
        for pulse_id, pulse in self.pulse_store._pulses.items():
            if pulse.actor_id != agent_id:
                continue
            if pulse.status != InterventionStatus.ACTIVE:
                continue

            # Observable action detected → mark pulse as resolved
            pulse.status = InterventionStatus.RESOLVED
            pulse.resolved_at = now
            pulse.details = pulse.details or {}
            pulse.details["auto_reset_evidence"] = evidence
            self.pulse_store.update_pulse(pulse)

            _log.info(
                "[AUTO-RESET] pulse_id=%s resolved for actor=%s via evidence: %s",
                pulse_id, agent_id, evidence[:80]
            )
            lifted += 1

        # Clear capability restriction
        if lifted > 0:
            self.pulse_store.clear_restriction(agent_id)
            _log.info(
                "[AUTO-RESET] Lifted restriction for actor=%s (evidence: %s)",
                agent_id, evidence[:80]
            )

            # Write auto-reset event to CIEU
            if self.cieu_store:
                try:
                    record = {
                        "event_id": str(uuid.uuid4()),
                        "seq_global": int(now * 1_000_000),
                        "created_at": now,
                        "session_id": "circuit_breaker_auto_reset",
                        "agent_id": agent_id,
                        "event_type": "circuit_breaker_auto_reset",
                        "decision": "allow",
                        "passed": True,
                        "violations": [],
                        "drift_detected": False,
                        "task_description": f"Auto-reset circuit breaker for {agent_id}: {evidence[:100]}",
                        "evidence_grade": "governance",
                    }
                    self.cieu_store.write_dict(record)
                except Exception as e:
                    _log.error("Failed to write auto-reset to CIEU: %s", e)

        return lifted
