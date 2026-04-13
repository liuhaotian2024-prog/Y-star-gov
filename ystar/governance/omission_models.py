"""
ystar.omission_models  —  Contractual Omission Governance: Core Data Models
============================================================================

防消极层的通用数据模型。不绑定任何具体业务角色（manager/worker/user）。
围绕六个抽象构建：Actor · Obligation · Trigger · RequiredEvent · DueTime · EscalationPolicy

    "既防乱来，也防不来。"
    —— 检查该发生却没发生的那类失败（omission failure）

与 Y* 现有架构的关系：
    engine.py        → 检查"做了不该做的"   (commission violation)
    omission_*.py    → 检查"没做该做的"     (omission violation)

两者共同构成完整的 contractual governance。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ── 枚举定义 ─────────────────────────────────────────────────────────────────

class EntityStatus(str, Enum):
    """通用交互单元生命周期状态机。"""
    CREATED     = "created"       # 已创建，尚未分配责任
    ASSIGNED    = "assigned"      # 已明确责任归属
    ACKNOWLEDGED= "acknowledged"  # 责任主体已确认
    ACTIVE      = "active"        # 正在推进
    BLOCKED     = "blocked"       # 被阻塞
    COMPLETED   = "completed"     # 执行完成
    PUBLISHED   = "published"     # 结果已向上游/外部正式发布
    CLOSED      = "closed"        # 生命周期结束
    EXPIRED     = "expired"       # 关键义务超时
    CANCELLED   = "cancelled"     # 被取消


class ObligationStatus(str, Enum):
    """义务状态机。"""
    PENDING       = "pending"        # 已创建，等待履行
    SOFT_OVERDUE  = "soft_overdue"   # v0.33: 软超时（已过 due_at，首次告警）
    HARD_OVERDUE  = "hard_overdue"   # v0.33: 硬超时（触发干预/阻断）
    FULFILLED     = "fulfilled"      # 已通过 required event 履行
    EXPIRED       = "expired"        # 最终超时（历史兼容，等同 hard_overdue）
    ESCALATED     = "escalated"      # 已升级
    CANCELLED     = "cancelled"      # 已取消（义务本身被撤销）
    FAILED        = "failed"         # Fix 6.3: 明确失败（cycle failure 触发）
    RESTORED      = "restored"       # v0.43: 过期后补救成功

    @property
    def is_open(self) -> bool:
        """义务是否仍处于未闭环状态。"""
        return self in (
            ObligationStatus.PENDING,
            ObligationStatus.SOFT_OVERDUE,
            ObligationStatus.HARD_OVERDUE,
        )

    @property
    def is_overdue_any(self) -> bool:
        return self in (
            ObligationStatus.SOFT_OVERDUE,
            ObligationStatus.HARD_OVERDUE,
            ObligationStatus.EXPIRED,
            ObligationStatus.ESCALATED,
        )


class OmissionType(str, Enum):
    """
    通用 omission 失败类型。
    注意：这些命名故意保持通用（不含 manager/worker 等角色词汇）。
    """
    REQUIRED_DELEGATION           = "required_delegation_omission"
    REQUIRED_ACKNOWLEDGEMENT      = "required_acknowledgement_omission"
    REQUIRED_STATUS_UPDATE        = "required_status_update_omission"
    REQUIRED_RESULT_PUBLICATION   = "required_result_publication_omission"
    REQUIRED_UPSTREAM_NOTIFICATION= "required_upstream_notification_omission"
    REQUIRED_ESCALATION           = "required_escalation_omission"
    REQUIRED_CLOSURE              = "required_closure_omission"

    # Directive #015 obligation types (used by default triggers)
    KNOWLEDGE_UPDATE_REQUIRED     = "knowledge_update_required"
    TOKEN_RECORDING_REQUIRED      = "token_recording_required"
    CASE_DOCUMENTATION_REQUIRED   = "case_documentation_required"
    TECHNICAL_REVIEW_REQUIRED     = "technical_review_required"
    PRE_COMMIT_TEST_REQUIRED      = "pre_commit_test_required"
    THINKING_DISCIPLINE_REQUIRED  = "thinking_discipline_required"
    CROSS_REVIEW_REQUIRED         = "cross_review_required"
    GIT_PUSH_REQUIRED             = "git_push_required"

    # Event-triggered obligations (Board directive 2026-04-03)
    COMMIT_PUSH_REQUIRED          = "commit_push_required"
    DISTRIBUTION_VERIFY_REQUIRED  = "distribution_verify_required"
    SOURCE_VERIFICATION_REQUIRED  = "source_verification_required"
    P0_BUG_FIX_REQUIRED           = "p0_bug_fix_required"
    P1_BUG_FIX_REQUIRED           = "p1_bug_fix_required"
    ESCALATION_RESPONSE_REQUIRED  = "escalation_response_required"
    SECURITY_INCIDENT_RESPONSE_REQUIRED = "security_incident_response_required"
    DIRECTIVE_DECOMPOSITION_REQUIRED = "directive_decomposition_required"

    # Test-only obligation types (used in test suite)
    TEST_OBLIGATION               = "test_obligation"
    OBLIGATION1                   = "obligation1"
    OBLIGATION2                   = "obligation2"
    INTEGRATION_OBLIGATION        = "integration_obligation"
    EXPIRY_OBLIGATION             = "expiry_obligation"
    # 通过 contract/domain pack 可扩展更多类型


class Severity(str, Enum):
    SOFT     = "soft"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class EscalationAction(str, Enum):
    REMINDER        = "reminder"
    VIOLATION       = "violation"
    ESCALATE        = "escalate"
    DENY_CLOSURE    = "deny_closure"
    SEVERITY_UPGRADE= "severity_upgrade"


# ── 核心数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class EscalationPolicy:
    """义务未履行时的升级策略。"""
    reminder_after_secs:   Optional[float] = None    # 多少秒后发 reminder
    violation_after_secs:  Optional[float] = None    # 多少秒后标为 violation
    escalate_after_secs:   Optional[float] = None    # 多少秒后上升升级
    actions:               List[EscalationAction] = field(
        default_factory=lambda: [EscalationAction.REMINDER, EscalationAction.VIOLATION]
    )
    escalate_to:           Optional[str] = None      # 升级目标 actor_id
    deny_closure_on_open:  bool = False              # 有未履行义务时拒绝 closure

    def to_dict(self) -> dict:
        return {
            "reminder_after_secs":  self.reminder_after_secs,
            "violation_after_secs": self.violation_after_secs,
            "escalate_after_secs":  self.escalate_after_secs,
            "actions":              [a.value for a in self.actions],
            "escalate_to":          self.escalate_to,
            "deny_closure_on_open": self.deny_closure_on_open,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EscalationPolicy":
        actions = [EscalationAction(a) for a in d.get("actions", [])]
        return cls(
            reminder_after_secs  = d.get("reminder_after_secs"),
            violation_after_secs = d.get("violation_after_secs"),
            escalate_after_secs  = d.get("escalate_after_secs"),
            actions              = actions or [EscalationAction.REMINDER, EscalationAction.VIOLATION],
            escalate_to          = d.get("escalate_to"),
            deny_closure_on_open = d.get("deny_closure_on_open", False),
        )

    @classmethod
    def default(cls) -> "EscalationPolicy":
        return cls(
            reminder_after_secs  = None,
            violation_after_secs = 1800.0,  # 30 分钟宽限期（与 deadline 一致）
            escalate_after_secs  = None,
            actions              = [EscalationAction.VIOLATION],
        )


@dataclass
class TrackedEntity:
    """
    通用"交互单元"或"责任单元"。
    兼容 task 但不绑定为 task。
    可代表：task / handoff / request / approval / workflow step / ...
    """
    entity_id:          str
    entity_type:        str                   # task / handoff / approval / request / ...
    initiator_id:       str                   # 创建者
    current_owner_id:   Optional[str]         # 当前责任人

    status:             EntityStatus = EntityStatus.CREATED
    goal_summary:       str = ""
    scope:              Dict[str, Any] = field(default_factory=dict)

    parent_entity_id:   Optional[str] = None  # 上级单元
    root_entity_id:     Optional[str] = None  # 根单元（用于 lineage）
    lineage:            List[str] = field(default_factory=list)  # [root → ... → self]

    contract_ref:       Optional[str] = None  # 关联的 contract/domain pack 引用
    required_next_event:Optional[str] = None  # 下一个期望事件类型
    required_by_ts:     Optional[float] = None # 下一个期望事件的截止时间

    deadline:           Optional[float] = None # 整体 deadline (Unix ts)
    created_at:         float = field(default_factory=time.time)
    updated_at:         float = field(default_factory=time.time)
    last_event_at:      Optional[float] = None

    metadata:           Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = time.time()
        self.last_event_at = self.updated_at

    def to_dict(self) -> dict:
        return {
            "entity_id":          self.entity_id,
            "entity_type":        self.entity_type,
            "initiator_id":       self.initiator_id,
            "current_owner_id":   self.current_owner_id,
            "status":             self.status.value,
            "goal_summary":       self.goal_summary,
            "scope":              self.scope,
            "parent_entity_id":   self.parent_entity_id,
            "root_entity_id":     self.root_entity_id,
            "lineage":            self.lineage,
            "contract_ref":       self.contract_ref,
            "required_next_event":self.required_next_event,
            "required_by_ts":     self.required_by_ts,
            "deadline":           self.deadline,
            "created_at":         self.created_at,
            "updated_at":         self.updated_at,
            "last_event_at":      self.last_event_at,
            "metadata":           self.metadata,
        }


@dataclass
class ObligationRecord:
    """
    某 actor 对某 entity 的一条具体义务记录。
    当 trigger 发生时创建；当 required event 出现时标为 fulfilled；
    到 due_at 仍为 pending 时标为 expired（omission violation）。
    """
    obligation_id:       str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id:           str = ""
    actor_id:            str = ""
    obligation_type:     str = ""           # OmissionType value 或自定义字符串

    trigger_event_id:    Optional[str] = None   # 触发该义务的事件 ID
    required_event_types:List[str] = field(default_factory=list)  # 满足义务需要的事件类型（任一即可）
    rule_id:             Optional[str] = None   # 创建此义务的规则 ID（用于审计和调试）

    due_at:              Optional[float] = None  # 截止时间 (Unix ts)
    grace_period_secs:   float = 0.0             # 宽限期（过了 due_at 再等多少秒才判定违规）

    status:              ObligationStatus = ObligationStatus.PENDING
    fulfilled_by_event_id: Optional[str] = None

    violation_code:      Optional[str] = None
    severity:            Severity = Severity.MEDIUM
    escalation_policy:   EscalationPolicy = field(default_factory=EscalationPolicy.default)
    escalated:           bool = False
    escalated_at:        Optional[float] = None

    # v0.33: Aging fields ────────────────────────────────────────────────────
    hard_overdue_secs:   float = 0.0             # 超过 due_at 多少秒触发 hard overdue
    soft_violation_at:   Optional[float] = None  # 首次软超时记录时间
    hard_violation_at:   Optional[float] = None  # 首次硬超时记录时间
    soft_count:          int = 0                 # 软超时告警累计次数（用于 severity 升级）

    # v0.43: Restoration fields ──────────────────────────────────────────────
    restoration_grace_period_multiplier: float = 2.0  # grace period 倍数（默认=原deadline的2倍）
    restored_at:         Optional[float] = None  # 恢复时间戳
    restored_by_event_id:Optional[str] = None    # 恢复事件 ID

    reminder_sent_at:    Optional[float] = None  # 已发送 reminder 的时间
    notes:               str = ""

    created_at:          float = field(default_factory=time.time)
    updated_at:          float = field(default_factory=time.time)

    # v0.48: Cancellation fields ─────────────────────────────────────────────
    session_id:          Optional[str] = None    # Session ID for boundary management
    cancelled_at:        Optional[float] = None  # Cancellation timestamp
    cancellation_reason: Optional[str] = None    # Why cancelled (session_ended, user_requested, etc.)

    @property
    def effective_due_at(self) -> Optional[float]:
        """考虑宽限期之后的实际判定截止时间。"""
        if self.due_at is None:
            return None
        return self.due_at + self.grace_period_secs

    def is_overdue(self, now: Optional[float] = None) -> bool:
        """是否已超过有效截止时间。"""
        if self.status != ObligationStatus.PENDING:
            return False
        eff = self.effective_due_at
        if eff is None:
            return False
        return (now or time.time()) > eff

    def restoration_deadline(self) -> Optional[float]:
        """计算恢复截止时间（原deadline + grace period * multiplier）。"""
        if self.due_at is None:
            return None
        deadline_secs = self.due_at - self.created_at
        return self.due_at + (deadline_secs * self.restoration_grace_period_multiplier)

    def can_restore(self, now: Optional[float] = None) -> bool:
        """检查是否仍在恢复宽限期内。"""
        if self.status not in (ObligationStatus.EXPIRED, ObligationStatus.HARD_OVERDUE,
                                ObligationStatus.SOFT_OVERDUE, ObligationStatus.ESCALATED):
            return False
        restoration_deadline = self.restoration_deadline()
        if restoration_deadline is None:
            return False
        return (now or time.time()) <= restoration_deadline

    def to_dict(self) -> dict:
        return {
            "obligation_id":        self.obligation_id,
            "entity_id":            self.entity_id,
            "actor_id":             self.actor_id,
            "obligation_type":      self.obligation_type,
            "trigger_event_id":     self.trigger_event_id,
            "required_event_types": self.required_event_types,
            "rule_id":              self.rule_id,
            "due_at":               self.due_at,
            "grace_period_secs":    self.grace_period_secs,
            "hard_overdue_secs":    self.hard_overdue_secs,
            "status":               self.status.value,
            "fulfilled_by_event_id":self.fulfilled_by_event_id,
            "violation_code":       self.violation_code,
            "severity":             self.severity.value,
            "escalation_policy":    self.escalation_policy.to_dict(),
            "escalated":            self.escalated,
            "escalated_at":         self.escalated_at,
            "soft_violation_at":    self.soft_violation_at,
            "hard_violation_at":    self.hard_violation_at,
            "soft_count":           self.soft_count,
            "restoration_grace_period_multiplier": self.restoration_grace_period_multiplier,
            "restored_at":          self.restored_at,
            "restored_by_event_id": self.restored_by_event_id,
            "reminder_sent_at":     self.reminder_sent_at,
            "notes":                self.notes,
            "created_at":           self.created_at,
            "updated_at":           self.updated_at,
        }


@dataclass
class GovernanceEvent:
    """
    omission governance 层消费的标准化事件。
    由 omission_adapter 从外部事件流转译而来，
    也可以由任何外部系统直接注入。
    """
    event_id:    str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type:  str = ""            # delegation_event / ack_event / status_event / ...
    entity_id:   str = ""
    actor_id:    str = ""
    ts:          float = field(default_factory=time.time)
    payload:     Dict[str, Any] = field(default_factory=dict)
    source:      str = "unknown"     # adapter / core / external / test
    lineage_ref: Optional[str] = None  # 关联的上级 entity 或 root

    def to_dict(self) -> dict:
        return {
            "event_id":   self.event_id,
            "event_type": self.event_type,
            "entity_id":  self.entity_id,
            "actor_id":   self.actor_id,
            "ts":         self.ts,
            "payload":    self.payload,
            "source":     self.source,
            "lineage_ref":self.lineage_ref,
        }


@dataclass
class RestorationResult:
    """
    恢复（restoration）操作的结果。
    """
    success:           bool = False
    obligation_id:     str = ""
    actor_id:          str = ""
    restored_at:       Optional[float] = None
    failure_reason:    Optional[str] = None  # beyond_grace_period / already_fulfilled / not_found / ...
    governance_event_id: Optional[str] = None  # 写入的 OBLIGATION_RESTORED 事件 ID

    def to_dict(self) -> dict:
        return {
            "success":            self.success,
            "obligation_id":      self.obligation_id,
            "actor_id":           self.actor_id,
            "restored_at":        self.restored_at,
            "failure_reason":     self.failure_reason,
            "governance_event_id":self.governance_event_id,
        }


@dataclass
class OmissionViolation:
    """
    一条 omission 违规记录。
    当 obligation 超期未履行时由 engine 创建，写入 CIEU。
    """
    violation_id:  str = field(default_factory=lambda: str(uuid.uuid4()))
    entity_id:     str = ""
    obligation_id: str = ""
    actor_id:      str = ""
    omission_type: str = ""           # OmissionType value

    detected_at:   float = field(default_factory=time.time)
    overdue_secs:  float = 0.0        # 超时了多少秒
    severity:      Severity = Severity.MEDIUM
    details:       Dict[str, Any] = field(default_factory=dict)

    escalated:     bool = False
    escalated_to:  Optional[str] = None
    cieu_ref:      Optional[str] = None  # 写入 CIEU 后的 event_id

    def to_dict(self) -> dict:
        return {
            "violation_id":  self.violation_id,
            "entity_id":     self.entity_id,
            "obligation_id": self.obligation_id,
            "actor_id":      self.actor_id,
            "omission_type": self.omission_type,
            "detected_at":   self.detected_at,
            "overdue_secs":  self.overdue_secs,
            "severity":      self.severity.value,
            "details":       self.details,
            "escalated":     self.escalated,
            "escalated_to":  self.escalated_to,
            "cieu_ref":      self.cieu_ref,
        }


# ── 预定义：标准 GovernanceEvent 类型常量 ────────────────────────────────────

class GEventType:
    """
    标准 GovernanceEvent 类型。
    这些是 omission engine 用来判定 obligation 是否被履行的事件类型。
    通过 contract/domain pack 可以自定义额外类型。
    """
    # 触发类（trigger）
    ENTITY_CREATED     = "entity_created"
    ENTITY_ASSIGNED    = "entity_assigned"
    ENTITY_BLOCKED     = "entity_blocked"
    RESULT_OBSERVED    = "result_observed"
    BLOCKER_DETECTED   = "blocker_detected"
    CLOSURE_PREREQ_MET = "closure_prereq_met"

    # 履行类（fulfillment）
    DELEGATION_EVENT        = "delegation_event"
    SELF_OWNERSHIP_EVENT    = "self_ownership_event"
    CLARIFICATION_EVENT     = "clarification_event"
    ACKNOWLEDGEMENT_EVENT   = "acknowledgement_event"
    DECLINE_EVENT           = "decline_event"
    STATUS_UPDATE_EVENT     = "status_update_event"
    BLOCKER_REPORT_EVENT    = "blocker_report_event"
    RESULT_PUBLICATION_EVENT= "result_publication_event"
    UPSTREAM_NOTIFY_EVENT   = "upstream_notify_event"
    ESCALATION_EVENT        = "escalation_event"
    CLOSURE_EVENT           = "closure_event"
    COMPLETION_EVENT        = "completion_event"

    # v0.33: Intervention events
    INTERVENTION_PULSE      = "intervention_pulse"
    OBLIGATION_GATE_DENY    = "obligation_gate_deny"
    FALLBACK_REROUTE        = "fallback_reroute"
    CAPABILITY_RESTRICTED   = "capability_restricted"
    CAPABILITY_RESTORED     = "capability_restored"

    # v0.43: Restoration events
    OBLIGATION_RESTORED     = "obligation_restored"

    # GOV-010 Phase 3: AutonomyEngine events (desire-driven layer)
    INTENT_DECLARED    = "intent_declared"
    PROGRESS_UPDATED   = "progress_updated"
    INTENT_COMPLETED   = "intent_completed"
    INTENT_STALLED     = "intent_stalled"
    GAP_IDENTIFIED     = "gap_identified"
    GAP_FILLED         = "gap_filled"

    # AMENDMENT-014: Prescriptive action queue events
    ACTION_PULLED      = "action_pulled"
    ACTION_QUEUE_RECOMPUTED = "action_queue_recomputed"
    OFF_TARGET_WARNING = "off_target_warning"
    ORPHAN_CLAIMED     = "orphan_claimed"

    # v0.50: gov_dispatch layer (task delegation governance)
    TASK_DISPATCHED    = "task_dispatched"      # dispatcher sends task to target_agent
    TASK_ACKNOWLEDGED  = "task_acknowledged"    # target_agent acknowledges receipt
    TASK_REJECTED      = "task_rejected"        # target_agent rejects (with reason)
    TASK_COMPLETED     = "task_completed"       # target_agent completes and reports
    DISPATCH_EXPIRED   = "dispatch_expired"     # acknowledgement timeout
