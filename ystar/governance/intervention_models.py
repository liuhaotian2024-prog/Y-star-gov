"""
ystar.intervention_models  —  Active Intervention Layer: Core Data Models
=========================================================================
v0.41.0

"从能看见失灵，升级到能逼交互链恢复规范。"

防消极层（omission_*.py）负责"发现断链"。
干预层（intervention_*.py）负责"对断链施加强制恢复脉冲"。

三级干预（不一次做满，只做可控的三级）：

  Level 1 — Soft Pulse（软干预）
    reminder / obligation-first prompt / next-step forcing
    ← 温柔提醒，不阻断执行

  Level 2 — Interrupt Gate（中干预）
    obligation-first gating: actor 有 hard overdue → 非义务动作 deny/redirect
    ← 不能继续乱跑，先交代欠的义务

  Level 3 — Reroute / Escalate（强干预）
    fallback owner / escalate to principal / capability restrict
    ← 持续不作为 → 自动改道
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── 枚举 ─────────────────────────────────────────────────────────────────────

class InterventionLevel(str, Enum):
    SOFT_PULSE        = "soft_pulse"         # Level 1: reminder, prompt
    INTERRUPT_GATE    = "interrupt_gate"     # Level 2: block non-obligation actions
    REROUTE_ESCALATE  = "reroute_escalate"   # Level 3: reassign / escalate


class InterventionActionType(str, Enum):
    # Level 1
    SEND_REMINDER         = "send_reminder"
    OBLIGATION_FIRST_PROMPT = "obligation_first_prompt"
    # Level 2
    GATE_DENY             = "gate_deny"         # non-obligation action denied
    GATE_REDIRECT         = "gate_redirect"     # redirected to fulfill obligation first
    CAPABILITY_RESTRICT   = "capability_restrict"  # restrict specific capabilities
    # Level 3
    ESCALATE_TO_PRINCIPAL = "escalate_to_principal"
    FALLBACK_OWNER        = "fallback_owner"    # reassign to fallback actor
    CAPABILITY_REVOKE     = "capability_revoke" # temporarily revoke capabilities


class GateDecision(str, Enum):
    ALLOW    = "allow"      # action proceeds normally
    DENY     = "deny"       # action blocked due to open critical obligation
    REDIRECT = "redirect"   # action redirected: fulfill obligation first


class InterventionStatus(str, Enum):
    ACTIVE   = "active"     # pulse is live
    RESOLVED = "resolved"   # actor fulfilled the obligation → pulse resolved
    EXPIRED  = "expired"    # pulse timed out without resolution
    ESCALATED= "escalated"  # escalated to higher level pulse


# ── 核心数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class CapabilityRestriction:
    """
    临时权限限制记录。
    对有 hard_overdue obligation 的 actor 暂时限制其能力范围。
    满足义务后自动恢复。
    """
    restriction_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    actor_id:          str = ""
    entity_id:         str = ""
    trigger_obligation_id: str = ""

    # 限制的动作类型标签——由适配层在注入时定义，内核不预设具体值
    restricted_actions: List[str] = field(default_factory=list)
    # 默认限制：spawn + write + exec（不限制 obligation fulfillment events）
    restricted_scopes:  List[str] = field(default_factory=list)

    active:             bool = True
    created_at:         float = field(default_factory=time.time)
    resolved_at:        Optional[float] = None
    resolved_reason:    Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "restriction_id":       self.restriction_id,
            "actor_id":             self.actor_id,
            "entity_id":            self.entity_id,
            "trigger_obligation_id":self.trigger_obligation_id,
            "restricted_actions":   self.restricted_actions,
            "restricted_scopes":    self.restricted_scopes,
            "active":               self.active,
            "created_at":           self.created_at,
            "resolved_at":          self.resolved_at,
        }


@dataclass
class InterventionPulse:
    """
    一次干预脉冲记录。
    由 InterventionEngine 在 omission violation 后产生，
    写入 CIEU，并驱动后续 gating / reroute / capability 动作。
    """
    pulse_id:             str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id:            str = ""
    actor_id:             str = ""
    trigger_obligation_id:str = ""
    omission_type:        str = ""

    level:                InterventionLevel = InterventionLevel.SOFT_PULSE
    actions:              List[InterventionActionType] = field(default_factory=list)

    triggered_at:         float = field(default_factory=time.time)
    resolved_at:          Optional[float] = None
    resolved_by_event_id: Optional[str] = None
    status:               InterventionStatus = InterventionStatus.ACTIVE

    # 强干预字段
    escalate_to:          Optional[str] = None   # principal / supervisor actor_id
    fallback_owner:       Optional[str] = None   # fallback actor_id
    capability_restriction: Optional[CapabilityRestriction] = None

    cieu_ref:             Optional[str] = None
    details:              Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "pulse_id":              self.pulse_id,
            "entity_id":             self.entity_id,
            "actor_id":              self.actor_id,
            "trigger_obligation_id": self.trigger_obligation_id,
            "omission_type":         self.omission_type,
            "level":                 self.level.value,
            "actions":               [a.value for a in self.actions],
            "triggered_at":          self.triggered_at,
            "resolved_at":           self.resolved_at,
            "resolved_by_event_id":  self.resolved_by_event_id,
            "status":                self.status.value,
            "escalate_to":           self.escalate_to,
            "fallback_owner":        self.fallback_owner,
            "cieu_ref":              self.cieu_ref,
            "details":               self.details,
        }


@dataclass
class GateCheckResult:
    """
    obligation-first gate 检查结果。
    在 enforce() 之前调用，决定该 action 是否被允许。
    """
    decision:        GateDecision = GateDecision.ALLOW
    actor_id:        str = ""
    action_type:     str = ""

    # 如果 DENY / REDIRECT：阻断原因
    blocking_obligation_id: Optional[str] = None
    blocking_omission_type: Optional[str] = None
    overdue_secs:           float = 0.0

    # 如果 REDIRECT：推荐的下一步
    suggested_action:       Optional[str] = None
    pulse_id:               Optional[str] = None  # 触发此 gate 的 pulse

    # GAP 4 FIX: Advisory causal recommendation (does NOT change gate decision)
    causal_recommendation:  Optional[str] = None

    @property
    def reason(self) -> Optional[str]:
        """Alias for blocking_omission_type for backward compatibility."""
        return self.blocking_omission_type

    def to_dict(self) -> dict:
        return {
            "decision":               self.decision.value,
            "actor_id":               self.actor_id,
            "action_type":            self.action_type,
            "blocking_obligation_id": self.blocking_obligation_id,
            "blocking_omission_type": self.blocking_omission_type,
            "overdue_secs":           self.overdue_secs,
            "suggested_action":       self.suggested_action,
            "pulse_id":               self.pulse_id,
            "causal_recommendation":  self.causal_recommendation,
        }


@dataclass
class InterventionResult:
    """一次 InterventionEngine 处理周期的输出汇总。"""
    pulses_fired:             List[InterventionPulse] = field(default_factory=list)
    pulses_resolved:          List[InterventionPulse] = field(default_factory=list)
    gates_denied:             int = 0
    gates_redirected:         int = 0
    reroutes:                 List[dict] = field(default_factory=list)
    capability_restrictions:  List[CapabilityRestriction] = field(default_factory=list)
    capability_restorations:  List[str] = field(default_factory=list)  # actor_ids restored

    def is_clean(self) -> bool:
        return (len(self.pulses_fired) == 0 and
                self.gates_denied == 0 and
                len(self.reroutes) == 0)

    def summary(self) -> str:
        parts = []
        if self.pulses_fired:
            by_level: Dict[str, int] = {}
            for p in self.pulses_fired:
                by_level[p.level.value] = by_level.get(p.level.value, 0) + 1
            parts.append("pulses: " + ", ".join(f"{k}×{v}" for k, v in by_level.items()))
        if self.gates_denied:
            parts.append(f"GATED×{self.gates_denied}")
        if self.gates_redirected:
            parts.append(f"REDIRECT×{self.gates_redirected}")
        if self.reroutes:
            parts.append(f"REROUTE×{len(self.reroutes)}")
        if self.capability_restrictions:
            parts.append(f"RESTRICTED×{len(self.capability_restrictions)}")
        return " | ".join(parts) if parts else "clean"
